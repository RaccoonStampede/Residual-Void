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
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np
from scipy.fft import rfft, rfftfreq
from scipy.signal import butter, filtfilt, find_peaks

BIT_DIM = 256
_STOP_TOKENS = set(
    "a an the of to in for on with is are was were be been being it this that "
    "these those and or but if as at by from into over after before about".split()
)
PHASE_OFFSET = 0.173
PHRASE_ANCHORS = {
    "diagnose": {"cause", "why", "diagnose", "symptom", "problem", "issue"},
    "quantity": {"how many", "count", "amount", "number", "total"},
    "conceptual": {"what is", "explain", "define", "meaning", "concept"},
    "tightness": {"exact", "specific", "strict", "verbatim", "literal"},
}
PHRASE_BRIDGES = {
    "treat": {"manage", "therapy", "care"},
    "diagnose": {"identify", "determine"},
    "heat": {"overheat", "hot", "temperature"},
    "storm": {"hurricane", "cyclone", "weather"},
    "count": {"number", "quantity", "many"},
}


def tokenize_text(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def content_tokens(text: str) -> List[str]:
    """Extract meaningful tokens (stopwords filtered)."""
    return [t for t in tokenize(text) if t not in _STOP_TOKENS and len(t) > 2]


def _stem_token(token: str) -> str:
    t = token.lower()
    for suffix in ("ing", "edly", "edly", "ed", "ies", "es", "s", "ment"):
        if t.endswith(suffix) and len(t) > len(suffix) + 2:
            if suffix == "ies":
                return t[:-3] + "y"
            return t[:-len(suffix)]
    return t


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, dele, sub))
        prev = cur
    return prev[-1]


def _jaro_winkler(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    max_dist = max(len(a), len(b)) // 2 - 1
    a_match = [False] * len(a)
    b_match = [False] * len(b)
    matches = 0
    transpositions = 0
    for i, ca in enumerate(a):
        start = max(0, i - max_dist)
        end = min(i + max_dist + 1, len(b))
        for j in range(start, end):
            if b_match[j] or b[j] != ca:
                continue
            a_match[i] = b_match[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    j = 0
    for i in range(len(a)):
        if not a_match[i]:
            continue
        while j < len(b) and not b_match[j]:
            j += 1
        if j < len(b) and a[i] != b[j]:
            transpositions += 1
        j += 1
    transpositions /= 2
    jaro = (
        (matches / len(a)) + (matches / len(b)) + ((matches - transpositions) / matches)
    ) / 3.0
    prefix = 0
    for ca, cb in zip(a, b):
        if ca == cb and prefix < 4:
            prefix += 1
        else:
            break
    return jaro + 0.1 * prefix * (1 - jaro)


def fuzzy_token_hits(query_tokens: Set[str], candidate_tokens: Set[str]) -> float:
    if not query_tokens or not candidate_tokens:
        return 0.0
    score = 0.0
    for qt in query_tokens:
        if qt in candidate_tokens:
            score += 1.0
            continue
        qstem = _stem_token(qt)
        best = 0.0
        for ct in candidate_tokens:
            if qstem == _stem_token(ct):
                best = max(best, 0.92)
            dist = _levenshtein(qt, ct)
            lev = 1.0 - dist / max(len(qt), len(ct), 1)
            jw = _jaro_winkler(qt, ct)
            best = max(best, lev * 0.55 + jw * 0.45)
        if best >= 0.78:
            score += best
    return score / max(1, len(query_tokens))


def classify_intent(query: str) -> str:
    q = query.lower().strip()
    for intent, anchors in PHRASE_ANCHORS.items():
        if any(a in q for a in anchors):
            return intent
    return "general"


def question_frequency(text: str) -> float:
    if not text:
        return 0.0
    qm = text.count("?")
    words = max(1, len(tokenize_text(text)))
    return min(1.0, qm / words * 8.0)


def text_to_frequencies(text: str) -> Dict[str, float]:
    toks = content_tokens(text)
    if not toks:
        return {}
    counts = Counter(_stem_token(t) for t in toks)
    total = float(sum(counts.values()))
    return {k: v / total for k, v in counts.items()}


def resonance_score(freqs_a: Dict[str, float], freqs_b: Dict[str, float]) -> float:
    if not freqs_a or not freqs_b:
        return 0.0
    base = cosine_similarity(Counter(freqs_a), Counter(freqs_b))
    offset = (math.sin((base + PHASE_OFFSET) * math.pi) + 1.0) / 2.0
    return float(0.75 * base + 0.25 * offset)


@dataclass
class RealityCore:
    vibration: float = 0.0
    coherence: float = 0.5
    steps: int = 0
    last_update: float = field(default_factory=time.time)

    def step(self, signal: float, intent: str = "general") -> float:
        self.steps += 1
        gain = 1.1 if intent in {"diagnose", "quantity"} else 1.0
        self.vibration = 0.8 * self.vibration + 0.2 * signal * gain
        self.coherence = float(np.clip(0.85 * self.coherence + 0.15 * abs(signal), 0.0, 1.0))
        self.last_update = time.time()
        return float(np.clip(0.5 * self.vibration + 0.5 * self.coherence, 0.0, 1.0))


def format_intent_answer(candidates: List[str], intent: str) -> str:
    if not candidates:
        return ""
    if intent == "quantity":
        return candidates[0]
    if intent == "tightness":
        return candidates[0]
    if intent == "diagnose":
        return " ".join(candidates[:2]).strip()
    if intent == "conceptual":
        return " || ".join(candidates[:3]).strip()
    return candidates[0] if len(candidates) == 1 else " || ".join(candidates[:3]).strip()


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
    shell: int = 0
    imprint_layer: str = "fast"
    coherence: float = 0.85
    value: float = 0.0
    freqs: Dict[str, float] = field(default_factory=dict)
    core: Optional[RealityCore] = None
    _sig_bits: np.ndarray = field(default=None, repr=False, compare=False)

    def bits(self) -> np.ndarray:
        if self._sig_bits is None:
            self._sig_bits = packed_to_bits(self.sig_packed)
        return self._sig_bits

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
        shell: int = 0,
        imprint_layer: str = "fast",
        coherence: float = 0.85,
        value: float = 0.0,
        freqs: Optional[Dict[str, float]] = None,
        core: Optional[RealityCore] = None,
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
                shell=shell,
                imprint_layer=imprint_layer,
                coherence=float(np.clip(coherence, 0.0, 1.0)),
                value=float(value),
                freqs=freqs or text_to_frequencies(text),
                core=core,
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

    def _primary_tag_hit(self, query: str, fragment: str) -> bool:
        q_tags = [t for t in query.split() if "::" in t]
        if not q_tags:
            return False
        frag_lower = fragment.lower()
        return any(tag.lower() in frag_lower for tag in q_tags)

    def _bridge_hits(self, qset: Set[str], cset: Set[str]) -> int:
        hits = 0
        for qt in qset:
            mapped = PHRASE_BRIDGES.get(qt, set())
            if mapped & cset:
                hits += 1
        return hits

    def rank(self, query: str, domain: Optional[str] = None, top_k: int = 20) -> List[tuple]:
        """Rank residuals with lexical, fuzzy, resonance, and value-aware heuristics."""
        with self._lock:
            if not self.residuals:
                return []
            probe = packed_to_bits(bytes_to_bits_packed(query.encode("utf-8")))
            qset = set(content_tokens(query))
            q_lower = query.lower().strip()
            qfreq = text_to_frequencies(query)
            q_intent = classify_intent(query)
            candidate_idxs: set = set()
            if qset:
                for t in qset:
                    candidate_idxs.update(self._token_index.get(t, []))
            if domain:
                candidate_idxs.update(self._domain_index.get(domain, []))
            if not candidate_idxs:
                candidate_idxs = set(range(len(self.residuals)))
            scores = []
            for i in candidate_idxs:
                res = self.residuals[i]
                r = hamming_sim(probe, res.bits())
                hits = sum(1 for t in qset if t in res.content_set) if qset else 0
                fuzzy_hits = fuzzy_token_hits(qset, res.content_set) if qset else 0.0
                bridge_hits = self._bridge_hits(qset, res.content_set)
                coverage = hits / max(1, len(qset)) if qset else 0.0
                resonance = resonance_score(qfreq, res.freqs)
                score = (
                    0.14 * r
                    + 0.24 * coverage
                    + 0.20 * fuzzy_hits
                    + 0.16 * resonance
                    + 0.08 * min(1.0, res.value)
                )
                frag_lower = res.fragment.lower()
                exact_sub = bool(q_lower and q_lower in frag_lower)
                if exact_sub:
                    score += 0.55
                elif any(t in frag_lower for t in qset if len(t) >= 3):
                    score += 0.22
                if self._primary_tag_hit(query, res.fragment):
                    score += 0.16
                if hits >= 2:
                    score += 0.18
                elif hits == 1:
                    score += 0.08
                if bridge_hits:
                    score += min(0.16, bridge_hits * 0.06)
                if "::" in res.fragment:
                    score += 0.08
                if domain and res.domain == domain:
                    score += 0.10
                if res.protect:
                    score += 0.02
                length_penalty = 0.0
                frag_len = len(res.fragment)
                if frag_len > 800:
                    length_penalty += 0.16
                elif frag_len > 400:
                    length_penalty += 0.08
                if "full" == q_intent and frag_len > 250:
                    length_penalty += 0.1
                density = hits / max(1, len(res.content_set))
                score += min(0.12, density * 0.4)
                specificity = len([t for t in res.content_set if len(t) > 5]) / max(1, len(res.content_set))
                score += min(0.1, specificity * 0.18)
                key_nouns = sum(1 for t in qset if len(t) > 4 and t in res.content_set)
                score += min(0.08, key_nouns * 0.03)
                if any(t in q_lower for t in ("how many", "count", "amount")):
                    if re.search(r"\b\d+(\.\d+)?\b", res.fragment):
                        score += 0.14
                if any(t in q_lower for t in ("why", "cause", "because", "reason")):
                    if any(k in frag_lower for k in ("because", "due to", "caused", "therefore")):
                        score += 0.12
                if any(t in q_lower for t in ("diagnose", "symptom", "treat")):
                    if any(k in frag_lower for k in ("symptom", "diagnose", "treat", "treatment")):
                        score += 0.10
                score -= length_penalty
                score += float(np.clip(res.value, -0.2, 0.2))
                lexical_signal = hits + (1 if exact_sub else 0)
                if lexical_signal == 0:
                    score *= 0.04
                elif coverage < 0.15 and fuzzy_hits < 0.3 and not exact_sub:
                    score *= 0.35
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
        self._query_log_limit = 3000

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

    def _log_query(self, query: str, source: str = "user") -> None:
        ok, _ = self.field.store(
            query,
            domain="query",
            node_id=source,
            protect=True,
            shell=0,
            imprint_layer="fast",
            coherence=0.99,
            value=0.0,
            freqs=text_to_frequencies(query),
        )
        if ok and len(self.field._domain_index.get("query", [])) > self._query_log_limit:
            # Bound query-chain index growth while preserving append-only residual history.
            self.field._domain_index["query"] = self.field._domain_index["query"][-self._query_log_limit:]

    def _vibrate_residuals(self, ranked: List[Tuple[Residual, float]], intent: str) -> List[Tuple[Residual, float]]:
        vibrated: List[Tuple[Residual, float]] = []
        for res, score in ranked:
            core = res.core or RealityCore()
            vib = core.step(score, intent=intent)
            res.core = core
            adjusted = float(np.clip(score * 0.82 + vib * 0.18, 0.0, 1.0))
            vibrated.append((res, adjusted))
        vibrated.sort(key=lambda x: -x[1])
        return vibrated

    def _bellman_update(self, winners: List[Residual], reward: float = 0.06) -> None:
        for res in winners:
            res.value = float(np.clip(0.88 * res.value + reward, -1.0, 1.0))

    def project(self, query: str, mode: str = "exact", source: str = "user") -> str:
        """Project query against locked residuals; returns fragment string or refusal."""
        self.project_count += 1
        self._log_query(query, source=source)
        ranked = self.field.rank(query)
        if not ranked or ranked[0][1] < self.min_score:
            self.invention_refusals += 1
            return self._REFUSAL
        q_lower = query.lower().strip()
        qset = set(content_tokens(query))
        if mode == "exact":
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
        if mode == "synthesize":
            intent = classify_intent(query)
            recover = self.field.rank(query, top_k=32)
            candidates = recover[:16]
            if qset:
                for res, score in recover[16:28]:
                    if score < 0.38:
                        continue
                    if fuzzy_token_hits(qset, res.content_set) >= 0.44:
                        candidates.append((res, score))
            if not candidates:
                self.invention_refusals += 1
                return self._REFUSAL
            candidates = self._vibrate_residuals(candidates, intent)
            preconceptual = []
            others = []
            for res, score in candidates:
                if res.imprint_layer in {"deep", "medium"} and res.coherence >= 0.88:
                    preconceptual.append((res, score + 0.03))
                else:
                    others.append((res, score))
            ordered = preconceptual + others
            def _intent_key(item: Tuple[Residual, float]) -> Tuple[float, float, float, float, float]:
                res, score = item
                frag = res.fragment.lower()
                diagnose = 1.0 if intent == "diagnose" and any(k in frag for k in ("symptom", "cause", "treat")) else 0.0
                quantity = 1.0 if intent == "quantity" and re.search(r"\b\d+(\.\d+)?\b", res.fragment) else 0.0
                conceptual = 1.0 if intent == "conceptual" and any(k in frag for k in ("is", "means", "defined")) else 0.0
                tightness = 1.0 if q_lower in frag else 0.0
                tag_hit = 1.0 if self.field._primary_tag_hit(query, res.fragment) else 0.0
                return (diagnose, quantity, conceptual, tightness, tag_hit + score)
            ordered.sort(key=_intent_key, reverse=True)
            top: List[str] = []
            seen: Set[str] = set()
            winners: List[Residual] = []
            for res, score in ordered:
                if score < 0.48:
                    continue
                if qset and fuzzy_token_hits(qset, res.content_set) < 0.20 and q_lower not in res.fragment.lower():
                    continue
                key = res.fragment[:120].lower()
                if key in seen:
                    continue
                seen.add(key)
                top.append(res.fragment.strip())
                winners.append(res)
                if len(top) >= 3:
                    break
            if not top:
                self.invention_refusals += 1
                return self._REFUSAL
            self._bellman_update(winners, reward=0.08 if intent in {"diagnose", "quantity"} else 0.05)
            answer = format_intent_answer(top, intent)
            if not answer:
                self.invention_refusals += 1
                return self._REFUSAL
            return answer
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
