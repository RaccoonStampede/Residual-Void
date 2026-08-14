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
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from scipy.fft import rfft, rfftfreq
from scipy.signal import butter, filtfilt, find_peaks

BIT_DIM = 256
_STOP_TOKENS = set(
    "a an the of to in for on with is are was were be been being it this that "
    "these those and or but if as at by from into over after before about".split()
)


def tokenize_text(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def content_tokens(text: str) -> List[str]:
    """Extract meaningful tokens (stopwords filtered)."""
    return [t for t in tokenize(text) if t not in _STOP_TOKENS and len(t) > 2]


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


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bytes_to_bits_packed(data: bytes) -> bytes:
    """Produce a 32-byte packed bit signature via multi-hash."""
    h1 = hashlib.sha256(data).digest()
    h2 = hashlib.sha256(data + b"|residual|void|binary|v2").digest()
    h3 = hashlib.blake2b(data, digest_size=32).digest()
    return (h1 + h2 + h3)[:32]


def bytes_to_bits(data: bytes, dim: int = BIT_DIM) -> np.ndarray:
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


def packed_to_bits(packed: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(packed, dtype=np.uint8)).astype(np.uint8)


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
# REALITY CORE OSCILLATOR
# ============================================================
@dataclass
class RealityCore:
    """Deterministic mean-field oscillator used for HyperDrive vibration reranking."""

    phase: float = 0.0
    vel: float = 0.0
    reference: float = 0.0
    scale: float = 1.0
    force: float = 0.0

    def __post_init__(self) -> None:
        s = max(self.scale, 1e-6)
        self.leak: float = 0.06 / (s ** 0.6)
        self.fluidity: float = 0.6 / (s ** 0.9)
        self.restore: float = 0.05 * (s ** 0.7)
        self.slow_leak: float = self.leak * 0.15

    def step(self, dt: float = 0.05) -> None:
        self.vel += dt * (
            self.force
            - self.restore * (self.phase - self.reference)
            - self.leak * self.vel
        )
        self.phase += dt * self.vel * self.fluidity
        self.reference += dt * self.slow_leak * (self.phase - self.reference)
        self.phase = float(np.clip(self.phase, -3.0, 3.0))
        self.vel = float(np.clip(self.vel, -2.0, 2.0))


# ============================================================
# FUZZY MATCHING HELPERS
# ============================================================
def _levenshtein(a: str, b: str) -> int:
    """True Levenshtein edit distance."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            )
        prev = curr
    return prev[len(b)]


def _jaro_winkler(s1: str, s2: str, p: float = 0.1) -> float:
    """Jaro-Winkler similarity."""
    if s1 == s2:
        return 1.0
    l1, l2 = len(s1), len(s2)
    if l1 == 0 or l2 == 0:
        return 0.0
    match_dist = max(l1, l2) // 2 - 1
    match_dist = max(match_dist, 0)
    s1_matches = [False] * l1
    s2_matches = [False] * l2
    matches = transpositions = 0
    for i in range(l1):
        start = max(0, i - match_dist)
        end = min(i + match_dist + 1, l2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = s2_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    k = 0
    for i in range(l1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    jaro = (matches / l1 + matches / l2 + (matches - transpositions / 2) / matches) / 3
    prefix = 0
    for i in range(min(4, l1, l2)):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break
    return jaro + prefix * p * (1 - jaro)


def fuzzy_token_hits(query_tokens: set, residual_tokens: set) -> float:
    """Hardened fuzzy token matching; returns weighted hit count."""
    total = 0.0
    for qt in query_tokens:
        for rt in residual_tokens:
            if qt == rt:
                total += 1.00
                break
            if (
                len(qt) >= 5 and len(rt) >= 5
                and abs(len(qt) - len(rt)) <= 2
                and (qt[:5] == rt[:5] or qt[-4:] == rt[-4:])
                and min(len(qt), len(rt)) / max(len(qt), len(rt)) >= 0.75
            ):
                total += 0.65
                break
            if (
                len(qt) >= 5 and len(rt) >= 5
                and _levenshtein(qt, rt) <= 1
                and _jaro_winkler(qt, rt) >= 0.93
            ):
                total += 0.70
                break
    return total


# ============================================================
# QUESTION FREQUENCY PROFILER
# ============================================================
_CAUSAL_WORDS = {"why", "cause", "because", "reason", "explain", "how", "mechanism", "lead", "result", "effect"}
_PROCESS_WORDS = {"how", "process", "step", "procedure", "method", "work", "operate", "function", "flow"}
_ENTITY_WORDS = {"who", "person", "author", "artist", "writer", "name", "character", "culture", "memoir", "people"}
_LOCATOR_WORDS = {"where", "location", "place", "city", "country", "region", "site"}
_SPECULATIVE_WORDS = {"could", "would", "might", "possible", "imagine", "hypothetical", "if", "suppose"}
_WHAT_WORDS = {"what", "which", "define", "describe", "meaning", "type"}
_FACTUAL_WORDS = {"when", "date", "year", "number", "amount", "much", "many"}
_DIAG_WORDS = {"residual", "void", "field", "coherent", "locked", "binary", "domain", "edge", "signal", "ground", "null"}


def question_frequency(query: str) -> Dict[str, Any]:
    """Return a frequency profile dict describing query intent class and biases."""
    toks = set(tokenize(query))
    lower = query.lower()

    causal = bool(toks & _CAUSAL_WORDS)
    process = bool(toks & _PROCESS_WORDS)
    entity = bool(toks & _ENTITY_WORDS)
    locator = bool(toks & _LOCATOR_WORDS)
    speculative = bool(toks & _SPECULATIVE_WORDS)
    what = bool(toks & _WHAT_WORDS)
    factual = bool(toks & _FACTUAL_WORDS)

    if causal:
        cls = "causal"
    elif process and not entity:
        cls = "process"
    elif entity:
        cls = "entity"
    elif locator:
        cls = "locator"
    elif speculative:
        cls = "speculative"
    elif what:
        cls = "what"
    elif factual:
        cls = "factual"
    else:
        cls = "neutral"

    diag_hits = len(toks & _DIAG_WORDS)
    diag_scale = min(1.0, 0.25 + 0.15 * diag_hits)

    fluct_open = 0.52 if cls in ("causal", "process") else 0.46
    soft_prefer = cls in ("entity", "what", "factual")
    process_bias = 0.12 if cls == "process" else (0.06 if cls == "causal" else 0.0)
    entity_bias = 0.10 if cls == "entity" else 0.0
    spec_penalty = 0.08 if speculative else 0.0

    return {
        "class": cls,
        "diag_scale": diag_scale,
        "fluct_open": fluct_open,
        "soft_prefer": soft_prefer,
        "process_bias": process_bias,
        "entity_bias": entity_bias,
        "speculative": spec_penalty,
    }


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
# LEAN RESIDUAL & COHERENT FIELD (hash-chain, no graph/mind)
# ============================================================
@dataclass
class Residual:
    """Permanent, append-only residual with cryptographic hash chain."""
    fragment: str
    sig_packed: bytes
    content_set: set
    domain: str
    timestamp: float
    version: int
    node_id: str
    residual_id: str
    prev_hash: str
    chain_hash: str
    protect: bool = True
    _sig_bits: np.ndarray = field(default=None, repr=False, compare=False)
    core: Optional["RealityCore"] = field(default=None, repr=False, compare=False)

    def bits(self) -> np.ndarray:
        """Lazy-cache unpacked signature bits."""
        if self._sig_bits is None:
            self._sig_bits = packed_to_bits(self.sig_packed)
        return self._sig_bits

    def ensure_core(self, scale: float = 1.0) -> "RealityCore":
        """Initialise a deterministic RealityCore seeded from the fragment hash."""
        if self.core is None:
            seed_val = int(hashlib.sha256(self.residual_id.encode()).hexdigest()[:8], 16)
            phase0 = ((seed_val % 1000) / 1000.0) * 2.0 - 1.0
            self.core = RealityCore(phase=phase0, scale=scale)
        return self.core

    # Convenience aliases kept for API compatibility
    @property
    def payload(self) -> str:
        return self.fragment

    @property
    def kind(self) -> str:
        return "text"


class CoherentField:
    """Append-only residual store with SHA-256 hash chain."""

    def __init__(self, dim: int = BIT_DIM):
        self.dim = dim
        self.residuals: List[Residual] = []
        self._exact_index: Dict[bytes, int] = {}
        self._token_index: Dict[str, List[int]] = defaultdict(list)
        self._domain_index: Dict[str, List[int]] = defaultdict(list)
        self._lock = threading.RLock()
        self._next_version = 1
        self.chain_tip: str = "GENESIS"

    def _raw_key(self, text: str) -> bytes:
        return hashlib.sha256(text.encode("utf-8")).digest()

    def _compute_chain_hash(self, fragment: str, prev_hash: str, residual_id: str, timestamp: float) -> str:
        payload = f"{prev_hash}|{residual_id}|{timestamp:.6f}|{fragment}".encode("utf-8")
        return sha256_hex(payload)

    def store(
        self,
        payload: Union[str, bytes],
        domain: str = "general",
        label: Optional[str] = None,
        node_id: str = "unknown",
        protect: bool = True,
    ) -> Tuple[bool, str]:
        """Store payload; returns (success, reason). Duplicate and short inputs are rejected."""
        with self._lock:
            if isinstance(payload, bytes):
                try:
                    text = payload.decode("utf-8").strip()
                except Exception:
                    return False, "decode_fail"
            else:
                text = str(payload).strip()
            if len(text) < 8:
                return False, "too_short"
            key = self._raw_key(text)
            if key in self._exact_index:
                return False, "duplicate"

            rid = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            sig_packed = bytes_to_bits_packed(text.encode("utf-8"))
            ts = time.time()
            prev = self.chain_tip
            chain_hash = self._compute_chain_hash(text, prev, rid, ts)

            res = Residual(
                fragment=text,
                sig_packed=sig_packed,
                content_set=set(content_tokens(text)),
                domain=domain,
                timestamp=ts,
                version=self._next_version,
                node_id=node_id,
                residual_id=rid,
                prev_hash=prev,
                chain_hash=chain_hash,
                protect=protect,
            )
            idx = len(self.residuals)
            self.residuals.append(res)
            self._exact_index[key] = idx
            self._domain_index[domain].append(idx)
            for t in res.content_set:
                self._token_index[t].append(idx)
            self._next_version += 1
            self.chain_tip = chain_hash
            return True, "locked"

    def verify_chain(self) -> Tuple[bool, str]:
        """Verify the cryptographic hash chain; returns (ok, message)."""
        with self._lock:
            if not self.residuals:
                return True, "empty chain ok"
            expected_prev = "GENESIS"
            for i, res in enumerate(self.residuals):
                if res.prev_hash != expected_prev:
                    return False, (
                        f"break at index {i}: expected prev {expected_prev[:16]}..."
                        f" got {res.prev_hash[:16]}..."
                    )
                recomputed = self._compute_chain_hash(
                    res.fragment, res.prev_hash, res.residual_id, res.timestamp
                )
                if recomputed != res.chain_hash:
                    return False, f"hash mismatch at index {i} (id={res.residual_id})"
                expected_prev = res.chain_hash
            if expected_prev != self.chain_tip:
                return False, "chain tip does not match last residual"
            return True, f"chain intact ({len(self.residuals)} residuals)"

    def rank(
        self,
        query: str,
        domain: Optional[str] = None,
        top_k: int = 20,
        freq: Optional[Dict[str, Any]] = None,
    ) -> List[tuple]:
        """Rank residuals by lexical + hamming similarity with freq-aware modulation."""
        with self._lock:
            if not self.residuals:
                return []
            if freq is None:
                freq = question_frequency(query)
            probe = packed_to_bits(bytes_to_bits_packed(query.encode("utf-8")))
            qset = set(content_tokens(query))
            q_lower = query.lower().strip()
            candidate_idxs: set = set()
            if qset:
                for t in qset:
                    candidate_idxs.update(self._token_index.get(t, []))
            if domain:
                candidate_idxs.update(self._domain_index.get(domain, []))
            if not candidate_idxs and not (qset or domain):
                candidate_idxs = set(range(len(self.residuals)))
            scores = []
            for i in candidate_idxs:
                res = self.residuals[i]
                r = hamming_sim(probe, res.bits())
                hits = sum(1 for t in qset if t in res.content_set) if qset else 0
                coverage = hits / max(1, len(qset)) if qset else 0.0
                score = 0.20 * r + 0.40 * coverage
                frag_lower = res.fragment.lower()
                exact_sub = bool(q_lower and q_lower in frag_lower)
                if exact_sub:
                    score += 0.55
                elif any(t in frag_lower for t in qset if len(t) >= 3):
                    score += 0.22
                if hits >= 2:
                    score += 0.18
                elif hits == 1:
                    score += 0.08
                if "::" in res.fragment:
                    score += 0.08
                if domain and res.domain == domain:
                    score += 0.10
                if res.protect:
                    score += 0.02

                # -- Diagnostic word set boost ---------------------------------
                diag_hits = len(res.content_set & _DIAG_WORDS)
                if diag_hits:
                    score += freq["diag_scale"] * min(1.0, diag_hits * 0.25)

                # -- Process bias ---------------------------------------------
                if freq["process_bias"] > 0:
                    proc_like = bool(res.content_set & _PROCESS_WORDS)
                    if proc_like:
                        score += freq["process_bias"]

                # -- Entity bias ----------------------------------------------
                if freq["entity_bias"] > 0:
                    entity_like = bool(res.content_set & (_ENTITY_WORDS | {"memoir", "culture"}))
                    if entity_like:
                        score += freq["entity_bias"]

                # -- Lexical dampening ----------------------------------------
                lexical_signal = hits + (1 if exact_sub else 0)
                if lexical_signal == 0:
                    score *= 0.03
                elif lexical_signal == 1 and not exact_sub:
                    score *= 0.68
                elif coverage < 0.15 and not exact_sub:
                    score *= 0.30

                # -- Fluctuation rescue (hamming strong, lexical weak) --------
                if lexical_signal == 0 and r > 0.58:
                    seed_val = int(res.residual_id[:4], 16) if res.residual_id[:4].isalnum() else 0
                    phase_factor = 0.85 + 0.15 * math.sin(seed_val * 0.017)
                    score = max(score, r * 0.30 * phase_factor)

                scores.append((res, float(min(1.0, score))))
            scores.sort(key=lambda x: -x[1])
            return scores[:top_k]

    def status(self) -> Dict[str, Any]:
        with self._lock:
            ok, msg = self.verify_chain()
            return {
                "residual_count": len(self.residuals),
                "chain_ok": ok,
                "chain_tip": self.chain_tip[:16] + "...",
            }


# ============================================================
# ENVELOPE AUTH (hub-style: nonce / iat / exp / kid / TTL / skew)
# ============================================================
class SecureNode:
    """Lean node: instance methods for lock/project, static methods for envelope auth."""

    def __init__(self, node_id: str, void: "CoherentVoid") -> None:
        self.node_id = node_id
        self.void = void
        self.secret = void.secret
        void.connect(node_id)

    # ------------------------------------------------------------------
    # Instance helpers
    # ------------------------------------------------------------------
    def lock_text(self, text: str, domain: str = "general", protect: bool = True) -> str:
        """Lock text via envelope auth then pass verified payload into lean ingest."""
        secret_str = self.secret if isinstance(self.secret, str) else self.secret.decode("utf-8")
        envelope = SecureNode.lock_payload(text, secret=secret_str)
        if not SecureNode.verify_payload(envelope, secret=secret_str):
            return "auth_failed"
        payload_bytes = text.encode("utf-8")
        to_sign = payload_bytes + b"lock" + domain.encode()
        secret_bytes = self.secret if isinstance(self.secret, bytes) else self.secret.encode("utf-8")
        sig = sign_packet(to_sign, secret_bytes)
        return self.void.ingest(
            "lock", payload_bytes, domain=domain, source=self.node_id,
            signature=sig, protect=protect,
        )

    def project(self, query: str, mode: str = "exact") -> str:
        return self.void.project(query, mode=mode, source=self.node_id)

    # ------------------------------------------------------------------
    # Static envelope helpers (hub-style)
    # ------------------------------------------------------------------
    @staticmethod
    def _kid(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def lock_payload(
        payload: Union[str, bytes],
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

        body: Dict[str, Any] = {
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


# ============================================================
# COHERENT VOID – lean dual-mode engine (exact / synthesize)
# ============================================================
class CoherentVoid:
    """Lean void engine: permanent residuals, hash chain, strict refusal gates."""

    _REFUSAL = "No locked residual in coherent void."

    def __init__(
        self,
        name: str = "void",
        secret: Union[str, bytes] = b"CHANGE-ME-32-BYTE-SECRET-KEY!!",
        min_project_score: float = 0.58,
        min_grounding: float = 0.35,
    ) -> None:
        self.name = name
        # Normalise secret: keep both bytes and str forms available
        if isinstance(secret, bytes):
            self.secret: bytes = secret
            self._secret: str = secret.decode("utf-8", errors="replace")
        else:
            self._secret = secret
            self.secret = secret.encode("utf-8")
        self.field = CoherentField()
        self.min_score = min_project_score
        self.min_grounding = min_grounding
        self._lock = threading.RLock()
        self.lock_count = 0
        self.project_count = 0
        self.invention_refusals = 0
        self.start_time = time.time()
        self.connected: Dict[str, float] = {}
        # HyperDrive synthesis settings
        self.vibrate_steps: int = 12
        self.vibrate_dt: float = 0.08
        self.coupling: float = 0.35

    def connect(self, system_id: str) -> str:
        with self._lock:
            self.connected[system_id] = time.time()
            return f"{system_id} connected"

    def ingest(
        self,
        action: str,
        payload: bytes,
        domain: str = "general",
        source: str = "unknown",
        label: Optional[str] = None,
        signature: Optional[bytes] = None,
        protect: bool = True,
    ) -> str:
        """Authenticated ingest; action must be 'lock' or 'confirm'."""
        with self._lock:
            if action in ("lock", "confirm"):
                if signature is None:
                    return "auth_failed"
                to_verify = payload + action.encode() + domain.encode()
                if not verify_signature(to_verify, signature, self.secret):
                    return "auth_failed"
                ok, reason = self.field.store(
                    payload, domain=domain, label=label, node_id=source, protect=protect
                )
                if ok:
                    self.lock_count += 1
                    return "locked"
                return reason
            return "ignored"

    # ------------------------------------------------------------------
    # HyperDrive: mean-field oscillator vibration reranking
    # ------------------------------------------------------------------
    def _vibrate_residuals(
        self, candidates: List[Tuple["Residual", float]]
    ) -> List[str]:
        """
        Short mean-field coupling loop over top grounded candidates.

        Each residual gets its own RealityCore seeded deterministically from
        its id.  After ``vibrate_steps`` coupling steps the combined oscillator
        coherence re-ranks candidates; returns up to 3 de-duplicated fragments.
        """
        pool = candidates[:6]
        if not pool:
            return []

        # Initialise / refresh cores
        for res, score in pool:
            c = res.ensure_core(scale=1.0 + score)
            c.force = score * 0.8  # initial drive proportional to rank score

        # Mean-field coupling loop
        for _ in range(self.vibrate_steps):
            mean_phase = sum(res.core.phase for res, _ in pool) / len(pool)
            for res, _ in pool:
                c = res.core
                c.force += self.coupling * (mean_phase - c.phase)
                c.step(dt=self.vibrate_dt)

        # Re-rank: blend original score with oscillator coherence
        def _coherence(core: RealityCore) -> float:
            # proximity of phase to reference = coherence signal
            return 1.0 / (1.0 + abs(core.phase - core.reference))

        ranked_vibrated = sorted(
            pool,
            key=lambda x: -(0.60 * x[1] + 0.40 * _coherence(x[0].core)),
        )

        # De-duplicate and return up to 3 fragments
        seen: set = set()
        result: List[str] = []
        for res, _ in ranked_vibrated:
            key = res.fragment[:80].lower()
            if key not in seen:
                seen.add(key)
                result.append(res.fragment.strip())
            if len(result) >= 3:
                break
        return result

    # ------------------------------------------------------------------
    # Main projection engine
    # ------------------------------------------------------------------
    def project(self, query: str, mode: str = "exact", source: str = "user") -> str:
        """Project query against locked residuals; returns fragment string or refusal."""
        self.project_count += 1
        freq = question_frequency(query)

        # Lock query into chain for traceability (domain="query")
        q_log = f"QUERY::{source}::{mode}|{freq['class']} | {query[:200]}"
        try:
            self.field.store(q_log, domain="query", node_id=source, protect=False)
        except Exception:
            pass

        ranked_raw = self.field.rank(query, freq=freq)
        # Exclude query-domain residuals from answer candidates
        ranked = [(r, s) for r, s in ranked_raw if r.domain != "query"]

        q_lower = query.lower().strip()
        qset = set(content_tokens(query))

        # ── EXACT MODE ───────────────────────────────────────────────
        if mode == "exact":
            if not ranked or ranked[0][1] < self.min_score:
                self.invention_refusals += 1
                return self._REFUSAL
            for res, score in ranked[:12]:
                if q_lower and q_lower in res.fragment.lower() and score >= 0.50:
                    return res.fragment
            top_res, top_score = ranked[0]
            hits = sum(1 for t in qset if t in top_res.content_set) if qset else 0
            exact_sub = bool(q_lower and q_lower in top_res.fragment.lower())
            if hits == 0 and not exact_sub:
                self.invention_refusals += 1
                return self._REFUSAL
            if top_score < 0.62 and hits < 2 and not exact_sub:
                self.invention_refusals += 1
                return self._REFUSAL
            return top_res.fragment

        # ── SYNTHESIZE MODE ──────────────────────────────────────────
        if mode == "synthesize":
            floor = 0.49
            candidates: List[Tuple[Residual, float]] = []
            seen: set = set()

            for res, score in ranked[:8]:
                if score < floor:
                    break
                hits = sum(1 for t in qset if t in res.content_set) if qset else 0
                exact_sub = bool(q_lower and q_lower in res.fragment.lower())
                has_anchor = "::" in res.fragment

                # Reject zero-hit / no-exact unless anchor
                if hits == 0 and not exact_sub and not has_anchor:
                    continue

                # Stricter single-hit threshold
                single_threshold = 0.49 if has_anchor else 0.58
                if hits <= 1 and not exact_sub and score < single_threshold:
                    continue

                frag_key = res.fragment[:80].lower()
                if frag_key not in seen:
                    seen.add(frag_key)
                    candidates.append((res, score))

            # Fluctuation recovery when no candidates from ranked pool
            if not candidates and not ranked:
                probe = packed_to_bits(bytes_to_bits_packed(query.encode("utf-8")))
                soft_pool: List[Tuple[Residual, float]] = []
                for res in self.field.residuals:
                    if res.domain == "query":
                        continue
                    r = hamming_sim(probe, res.bits())
                    fhits = fuzzy_token_hits(qset, res.content_set)
                    base = 0.30 * r + 0.40 * (fhits / max(1, len(qset)))
                    soft_pool.append((res, base))
                soft_pool.sort(key=lambda x: -x[1])

                open_thr = freq["fluct_open"] - freq["speculative"]
                for res, base in soft_pool[:6]:
                    c = res.ensure_core(scale=1.0)
                    c.force = base
                    for _ in range(self.vibrate_steps // 2):
                        c.step(dt=self.vibrate_dt)
                    coherence_val = 1.0 / (1.0 + abs(c.phase - c.reference))
                    combined = 0.55 * base + 0.45 * coherence_val * base
                    # Causal queries need diagnostic language
                    if freq["class"] == "causal":
                        if not (res.content_set & _DIAG_WORDS):
                            continue
                    frag_key = res.fragment[:80].lower()
                    if combined >= open_thr and frag_key not in seen:
                        # Final soft floor
                        if combined >= 0.32:
                            seen.add(frag_key)
                            candidates.append((res, combined))

            if not candidates:
                self.invention_refusals += 1
                return self._REFUSAL

            vibrated = self._vibrate_residuals(candidates)
            if not vibrated:
                self.invention_refusals += 1
                return self._REFUSAL
            return vibrated[0] if len(vibrated) == 1 else " || ".join(vibrated)

        return "Unknown mode"

    def verify_integrity(self) -> Tuple[bool, str]:
        """Verify hash chain integrity."""
        return self.field.verify_chain()

    def status(self) -> Dict[str, Any]:
        ok, msg = self.verify_integrity()
        return {
            "void": self.name,
            "locked": len(self.field.residuals),
            "lock_count": self.lock_count,
            "project_count": self.project_count,
            "refusals": self.invention_refusals,
            "chain_ok": ok,
            "chain_msg": msg,
            "chain_tip": self.field.chain_tip[:16] + "...",
            "nodes": list(self.connected.keys()),
            "uptime_sec": round(time.time() - self.start_time, 1),
        }
