from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import threading
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.fft import rfft, rfftfreq
from scipy.signal import butter, filtfilt, find_peaks


def tokenize_text(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def content_tokens(text: str) -> List[str]:
    """Extract meaningful tokens (stopwords filtered)."""
    stop = {"a", "an", "the", "of", "to", "in", "for", "on", "with", "is", "are", "was", "were", "be", "it", "this", "that", "and", "or"}
    return [t for t in tokenize_text(text) if t not in stop and len(t) > 2]


def cosine_similarity(vec_a: Counter, vec_b: Counter) -> float:
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(vec_a[key] * vec_b.get(key, 0) for key in vec_a)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bytes_to_bits(data: bytes, dim: int = 256) -> np.ndarray:
    """Convert bytes to bit vector using multi-hash (SHA256 + Blake2b)."""
    h1 = hashlib.sha256(data).digest()
    h2 = hashlib.sha256(data + b"|residual|void|binary|v2").digest()
    h3 = hashlib.blake2b(data, digest_size=32).digest()
    combined = h1 + h2 + h3
    bits = np.unpackbits(np.frombuffer(combined, dtype=np.uint8))
    if len(bits) < dim:
        extra = np.unpackbits(np.frombuffer(hashlib.sha256(combined).digest(), dtype=np.uint8))
        bits = np.concatenate([bits, extra])
    return bits[:dim].astype(np.uint8)


def hamming_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Hamming similarity between bit vectors."""
    return 1.0 - np.count_nonzero(a != b) / max(1, len(a))


def hamming_distance_hex(hex_a: str, hex_b: str) -> int:
    if len(hex_a) != len(hex_b):
        raise ValueError("Hex strings must have equal length")
    return sum((int(a, 16) ^ int(b, 16)).bit_count() for a, b in zip(hex_a, hex_b))


def canonical_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def hmac_sign(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def hmac_verify(secret: str, message: str, signature: str) -> bool:
    expected = hmac_sign(secret, message)
    return hmac.compare_digest(expected, signature)


def sign_packet(payload: bytes, secret: bytes) -> bytes:
    """Sign packet with HMAC-SHA256."""
    return hmac.new(secret, payload, hashlib.sha256).digest()


def verify_signature(payload: bytes, signature: bytes, secret: bytes) -> bool:
    """Verify HMAC signature."""
    expected = sign_packet(payload, secret)
    return hmac.compare_digest(expected, signature)


# ============================================================
# PI-HELIX v2 EDGE EXTRACTION
# ============================================================
def schumann_carrier(t, f0=7.83, harmonics=5):
    """Generate Schumann resonance carrier (7.83 Hz)."""
    s = np.zeros_like(t, dtype=float)
    for h in range(1, harmonics + 1):
        s += (1.0 / h) * np.sin(2 * np.pi * f0 * h * t)
    return s / (np.max(np.abs(s)) + 1e-12)


def pi_helix_drive(t, f0=1.0, gamma=0.05):
    """Golden ratio drive signal (φ-based)."""
    phi = (np.sqrt(5) - 1) / 2
    theta = 2 * np.pi * f0 * t
    helix = np.sin(theta + np.pi * t) * np.cos(np.deg2rad(5) * theta)
    envelope = np.exp(-phi * 0.07 * t) * (1.0 - gamma) + gamma * 0.12 * np.random.randn(len(t))
    return helix * envelope


def bandpass(data, fs, low, high, order=4):
    nyq = 0.5 * fs
    low = max(low / nyq, 1e-5)
    high = min(high / nyq, 0.999)
    if low >= high:
        return data
    b, a = butter(order, [low, high], btype='band')
    return filtfilt(b, a, data)


def highpass(data, fs, cutoff=25.0, order=6):
    nyq = 0.5 * fs
    normal = min(max(cutoff / nyq, 1e-5), 0.999)
    b, a = butter(order, normal, btype='high')
    return filtfilt(b, a, data)


def extract_multi_band(residual, fs, bands):
    """Extract frequency peaks from multi-band residual."""
    results = {}
    n = len(residual)
    window = np.hanning(n)
    for name, low, high in bands:
        try:
            band_data = bandpass(residual, fs, low, high) if (low > 0 or high < fs/2) else residual
        except Exception:
            band_data = residual
        spectrum = np.abs(rfft(band_data * window))
        freqs = rfftfreq(n, d=1.0/fs)
        mask = (freqs >= low) & (freqs <= high)
        if not np.any(mask) or len(spectrum[mask]) < 5:
            results[name] = []
            continue
        sub_spec = spectrum[mask]
        sub_freq = freqs[mask]
        peaks, _ = find_peaks(sub_spec, height=np.max(sub_spec)*0.08, distance=4)
        if len(peaks) == 0:
            results[name] = []
            continue
        order = np.argsort(sub_spec[peaks])[::-1]
        top = [(float(sub_freq[peaks[i]]), float(sub_spec[peaks[i]])) for i in order[:5]]
        results[name] = top
    return results


def build_core_negative_v2(measured, fs, max_harmonics=8, max_lag=80):
    """Core nulling via Schumann + Pi-Helix drives."""
    t = np.arange(len(measured)) / fs
    residual = measured.copy().astype(float)
    total_neg = np.zeros_like(residual)
    f0 = 7.83
    
    # Harmonic basis projection
    basis = [np.sin(2 * np.pi * f0 * h * t) for h in range(1, max_harmonics + 1)]
    basis += [np.cos(2 * np.pi * f0 * h * t) for h in range(1, max_harmonics + 1)]
    basis = np.stack(basis, axis=1)
    try:
        coef = np.linalg.lstsq(basis, residual, rcond=None)[0]
        proj = basis @ coef
        residual = residual - proj
        total_neg = total_neg - proj
    except Exception:
        pass
    
    # Schumann nulling
    schumann = schumann_carrier(t)
    best_score = np.inf
    best_neg = np.zeros_like(residual)
    for lag in range(-max_lag, max_lag + 1, 2):
        shifted = np.roll(schumann, lag)
        denom = np.dot(shifted, shifted) + 1e-12
        scale = np.dot(residual, shifted) / denom
        candidate = -scale * shifted
        score = np.sum((residual + candidate)**2)
        if score < best_score:
            best_score = score
            best_neg = candidate
    residual = residual + best_neg
    total_neg = total_neg + best_neg
    
    # Pi-Helix nulling
    drive = pi_helix_drive(t, gamma=0.03)
    best_score = np.inf
    best_neg = np.zeros_like(residual)
    for lag in range(-40, 41, 2):
        shifted = np.roll(drive, lag)
        denom = np.dot(shifted, shifted) + 1e-12
        scale = np.dot(residual, shifted) / denom
        candidate = -scale * shifted
        score = np.sum((residual + candidate)**2)
        if score < best_score:
            best_score = score
            best_neg = candidate
    residual = residual + best_neg
    residual = highpass(residual, fs, cutoff=25.0, order=6)
    return residual, total_neg


def hierarchical_edge_extract_v2(measured, fs, gamma=0.05):
    """Hierarchical edge extraction (Pi-Helix v2)."""
    residual, _ = build_core_negative_v2(measured, fs)
    residual -= np.mean(residual)
    residual /= (np.std(residual) + 1e-12)
    bands = [
        ("field_substrate", 0.5, 35.0),
        ("cytoskeleton", 35.0, 250.0),
        ("bioelectric", 250.0, 1200.0),
        ("cognition", 1200.0, max(fs/2 - 20, 1300)),
    ]
    return residual, extract_multi_band(residual, fs, bands)


# ============================================================
# RESIDUAL & FIELD
# ============================================================
@dataclass
class Residual:
    residual_id: str
    kind: str
    payload: str
    tokens: List[str]
    token_vector: Counter
    created_at: float
    sig: np.ndarray  # bit signature
    content_set: set
    domain: str = "general"
    metadata: Dict[str, Any] = field(default_factory=dict)


class CoherentField:
    def __init__(self, graph_similarity_threshold: float = 0.2, dim: int = 256, max_neighbors: int = 7):
        self._residuals: List[Residual] = []
        self._exact_index: Dict[bytes, int] = {}
        self._token_index: Dict[str, List[int]] = defaultdict(list)
        self._domain_index: Dict[str, List[int]] = defaultdict(list)
        self._adjacency: np.ndarray = np.zeros((0, 0), dtype=float)
        self._graph_similarity_threshold = graph_similarity_threshold
        self.adj: Dict[int, List[Tuple[int, float]]] = defaultdict(list)
        self.graph_dirty = True
        self.dim = dim
        self.max_neighbors = max_neighbors
        self._lock = threading.RLock()
        self.last_lambda2 = 0.0

    def _raw_key(self, raw: bytes) -> bytes:
        return hashlib.sha256(raw).digest()

    def _rebuild_graph(self):
        self.adj.clear()
        n = len(self._residuals)
        if n < 2:
            self.graph_dirty = False
            return
        for i in range(n):
            sims = []
            for j in range(n):
                if i == j:
                    continue
                s = hamming_sim(self._residuals[i].sig, self._residuals[j].sig)
                if s >= self._graph_similarity_threshold:
                    sims.append((j, s))
            sims.sort(key=lambda x: -x[1])
            self.adj[i] = sims[:self.max_neighbors]
        self.graph_dirty = False

    def store(self, payload: str | bytes, kind: str = "text", domain: str = "general", metadata: Optional[Dict[str, Any]] = None) -> Residual:
        with self._lock:
            if isinstance(payload, bytes):
                normalized = base64.b64encode(payload).decode("ascii")
                inferred_kind = "binary"
            else:
                normalized = payload
                inferred_kind = kind

            tokens = tokenize_text(normalized)
            created_at = time.time()
            residual_id = hash_text(f"{inferred_kind}:{normalized}:{created_at}")
            
            # Bit signature
            sig = bytes_to_bits(normalized.encode("utf-8") if isinstance(normalized, str) else normalized, dim=self.dim)
            
            residual = Residual(
                residual_id=residual_id,
                kind=inferred_kind,
                payload=normalized,
                tokens=tokens,
                token_vector=Counter(tokens),
                created_at=created_at,
                sig=sig,
                content_set=set(content_tokens(normalized)),
                domain=domain,
                metadata=metadata or {},
            )
            self._residuals.append(residual)
            key = self._raw_key(normalized.encode("utf-8") if isinstance(normalized, str) else normalized)
            self._exact_index[key] = len(self._residuals) - 1
            self._domain_index[domain].append(len(self._residuals) - 1)
            for t in residual.content_set:
                self._token_index[t].append(len(self._residuals) - 1)
            self.graph_dirty = True
            return residual

    def rank(self, query: str, top_k: int = 5, use_mp: bool = True, mp_layers: int = 1, mp_alpha: float = 0.30) -> List[Tuple[Residual, float]]:
        with self._lock:
            if not self._residuals:
                return []
            if self.graph_dirty:
                self._rebuild_graph()
            
            probe = bytes_to_bits(query.encode("utf-8"), self.dim)
            qset = set(content_tokens(query))
            
            candidate_idxs = set()
            if qset:
                for t in qset:
                    candidate_idxs.update(self._token_index.get(t, []))
            if not candidate_idxs:
                candidate_idxs = set(range(len(self._residuals)))
            
            base_scores = {}
            for i in candidate_idxs:
                res = self._residuals[i]
                r = hamming_sim(probe, res.sig)
                hits = sum(1 for t in qset if t in res.content_set) if qset else 0
                coverage = hits / max(1, len(qset)) if qset else 0.0
                score = 0.50 * r + 0.50 * coverage
                if hits >= 2:
                    score += 0.12
                if hits >= 3:
                    score += 0.05
                base_scores[i] = float(min(1.0, score))
            
            if use_mp and self.adj and mp_layers > 0:
                scores = dict(base_scores)
                for _ in range(mp_layers):
                    new_scores = {}
                    for i in scores:
                        agg = wsum = 0.0
                        for j, w in self.adj.get(i, []):
                            if j in scores:
                                agg += w * scores[j]
                                wsum += w
                        new_scores[i] = (1.0 - mp_alpha) * scores[i] + mp_alpha * (agg / wsum) if wsum > 0 else scores[i]
                    scores = new_scores
                final = [(self._residuals[i], s) for i, s in scores.items()]
            else:
                final = [(self._residuals[i], s) for i, s in base_scores.items()]
            
            final.sort(key=lambda x: -x[1])
            return final[:top_k]

    def compute_laplacian_spectrum(self, k: int = 5) -> Dict:
        with self._lock:
            if self.graph_dirty:
                self._rebuild_graph()
            n = len(self._residuals)
            if n < 3:
                return {"n": n, "lambda2": 0.0, "multiplicity0": n, "evals": []}
            
            rows, cols, data = [], [], []
            for i, nbrs in self.adj.items():
                for j, w in nbrs:
                    rows += [i, j]
                    cols += [j, i]
                    data += [w, w]
            
            if not rows:
                return {"n": n, "lambda2": 0.0, "multiplicity0": n, "evals": []}
            
            from scipy.sparse import csr_matrix
            from scipy.sparse.linalg import eigsh
            
            A = csr_matrix((data, (rows, cols)), shape=(n, n))
            degrees = np.array(A.sum(axis=1)).flatten()
            D = csr_matrix((degrees, (range(n), range(n))), shape=(n, n))
            L = D - A
            
            try:
                evals = eigsh(L, k=min(k, n-1), which='SM', return_eigenvectors=False)
                evals = np.sort(np.real(evals))
                mult0 = int(np.sum(np.abs(evals) < 1e-6))
                lambda2 = float(evals[1]) if len(evals) > 1 else 0.0
                self.last_lambda2 = lambda2
                return {"n": n, "lambda2": lambda2, "multiplicity0": mult0, "evals": [float(e) for e in evals[:k]]}
            except Exception as e:
                return {"n": n, "lambda2": 0.0, "multiplicity0": 0, "evals": [], "error": str(e)}

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "residual_count": len(self._residuals),
                "graph_nodes": int(self._adjacency.shape[0]),
                "graph_edges": int(np.count_nonzero(np.triu(self._adjacency, k=1))),
            }


class SecureNode:
    @staticmethod
    def _kid(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def lock_payload(
        payload: str | bytes,
        secret: str,
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: int = 30,
        skew_seconds: int = 10,
    ) -> Dict[str, Any]:
        now = int(time.time())
        if isinstance(payload, bytes):
            encoded_payload = base64.b64encode(payload).decode("ascii")
            kind = "binary"
        else:
            encoded_payload = payload
            kind = "text"

        body = {
            "payload": encoded_payload,
            "kind": kind,
            "iat": now,
            "timestamp": now,
            "exp": now + ttl_seconds,
            "nonce": uuid.uuid4().hex,
            "kid": SecureNode._kid(secret),
            "metadata": metadata or {},
        }
        serialized = canonical_payload(body)
        body["signature"] = hmac_sign(secret, serialized)
        return body

    @staticmethod
    def verify_payload(
        payload: Dict[str, Any],
        secret: str,
        ttl_seconds: int = 30,
        skew_seconds: int = 10,
        previous_secret: Optional[str] = None,
    ) -> bool:
        candidates = [secret]
        if previous_secret and previous_secret != secret:
            candidates.append(previous_secret)

        for candidate in candidates:
            signature = payload.get("signature", "")
            body = {k: v for k, v in payload.items() if k != "signature"}
            serialized = canonical_payload(body)

            if not signature or not hmac_verify(candidate, serialized, signature):
                continue

            timestamp = payload.get("iat")
            if timestamp is None:
                timestamp = payload.get("timestamp")
            if not isinstance(timestamp, int):
                continue

            exp = payload.get("exp")
            if not isinstance(exp, int):
                continue

            nonce = payload.get("nonce")
            kid = payload.get("kid")
            if not isinstance(nonce, str) or not nonce:
                continue
            if not isinstance(kid, str) or kid != SecureNode._kid(candidate):
                continue

            now = int(time.time())
            if timestamp > now + skew_seconds:
                continue
            if exp < now - skew_seconds:
                continue
            if now - timestamp > ttl_seconds + skew_seconds:
                continue

            return True

        return False


class CoherentVoid:
    def __init__(self, secret: str, min_project_score: float = 0.2) -> None:
        self._secret = secret
        self._field = CoherentField()
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._min_project_score = min_project_score
        self._lock = threading.RLock()

    def authenticated_ingest_lock(self, payload: Dict[str, Any]) -> Optional[str]:
        if not SecureNode.verify_payload(payload, self._secret):
            return None

        lock_id = hash_text(canonical_payload(payload))
        with self._lock:
            self._pending[lock_id] = payload
        return lock_id

    def confirm(self, lock_id: str) -> Optional[Residual]:
        with self._lock:
            payload = self._pending.pop(lock_id, None)
        if payload is None:
            return None

        kind = payload.get("kind", "text")
        content = payload.get("payload", "")
        if kind == "binary":
            decoded = base64.b64decode(content.encode("ascii"))
            return self._field.store(decoded, kind=kind, metadata=payload.get("metadata") or {})
        return self._field.store(str(content), kind=kind, metadata=payload.get("metadata") or {})

    def project(self, query: str, top_k: int = 3, require_grounding: bool = True) -> List[Tuple[Residual, float]]:
        ranked = self._field.rank(query, top_k=top_k, use_mp=True)
        if not ranked:
            return []
        if ranked[0][1] < self._min_project_score:
            return []
        if require_grounding and not self._is_grounded(ranked):
            return []
        return ranked

    def _is_grounded(self, ranked) -> bool:
        if not ranked:
            return False
        return any(score >= self._min_project_score for _, score in ranked)

    def status(self) -> Dict[str, Any]:
        return {
            "pending_locks": len(self._pending),
            "min_project_score": self._min_project_score,
            "field": self._field.status(),
        }

    @property
    def field(self) -> CoherentField:
        return self._field
