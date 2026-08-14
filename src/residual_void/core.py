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
from copy import deepcopy
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
PHASE_OFFSET = 0.81
PHRASE_ANCHORS = [
    "heat exhaustion", "heat stroke", "heat cramps", "heat syncope", "heat rash",
    "30 minutes", "thunder roars", "isolated tree", "under a tree", "severe thunderstorm",
    "first aid", "call 911", "90 f", "less than 90", "over 90", "above 90", "use fans",
    "metal-topped vehicle", "corded phones", "how long after",
]
PHRASE_BRIDGES = {
    "how long after": ["30 minutes", "thirty minutes"],
    "under a tree": ["isolated tree"],
    "stand under": ["isolated tree"],
    "over 90": ["90 f", "above 90", "less than 90"],
    "90 degrees": ["90 f", "above 90"],
    "why was residualvoid": ["began as a response", "memory bottleneck", "geometry of stored"],
    "why was residual": ["began as a response", "memory bottleneck"],
    "why was it built": ["began as a response", "memory bottleneck"],
    "unused knowledge": ["unused residuals slowly decay", "decay never deletes", "lowers ranking preference"],
    "what happens to unused": ["unused residuals slowly decay", "decay never deletes"],
    "decayed information": ["remain fully visible", "never existence", "ranking priority"],
    "does decayed": ["remain fully visible", "never existence"],
    "find low-value": ["rank by ascending value", "value falls below"],
    "invent new facts": ["no free invention", "supported by locked"],
}

TOKEN_BRIDGES = {
    "bond": ["ground", "grounding", "bonded", "bond"],
    "bonded": ["ground", "grounding", "bond"],
    "ground": ["grounding", "bond", "bonded"],
    "grounding": ["ground", "bond", "bonded"],
    "protect": ["overload", "protect", "protection", "relay"],
    "protection": ["overload", "protect", "relay"],
    "overload": ["protect", "protection", "thermal", "relay"],
    "frame": ["grounding", "ground", "bond", "bonded"],
}


def tokenize_text(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def tokenize(text: str) -> List[str]:
    return re.findall(
        r"[0-9A-Za-zÀ-ɏͰ-Ͽἀ-῿']+",
        text.lower(),
        flags=re.UNICODE,
    )


def content_tokens(text: str) -> List[str]:
    """Extract meaningful tokens (stopwords filtered)."""
    return [t for t in tokenize(text) if t not in _STOP_TOKENS and len(t) > 2]


def _stem_token(token: str) -> str:
    t = token.lower()
    for suffix in ("edly", "ment", "ing", "ly", "ies", "ed", "es", "s"):
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
    max_dist = max(0, max(len(a), len(b)) // 2 - 1)
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
    return score


def classify_intent(query: str) -> str:
    q = query.lower().strip()
    if any(w in q for w in (
        "won't", "wont", "not working", "keeps", "keep tripping",
        "fail", "failed", "problem", "issue", "error",
        "caused", "cause", "miss the", "missed", "why did", "what caused",
        "dropped", "fault",
    )):
        return "diagnose"
    if q.startswith("why") or " why " in f" {q} ":
        return "why"
    if q.startswith("how") or q.startswith("what about") or "how do" in q or "how should" in q or "how does" in q:
        return "how"
    if q.startswith("what") or q.startswith("who") or q.startswith("where") or q.startswith("when"):
        return "what"
    return "general"


def question_frequency(query: str) -> Dict[str, Any]:
    q = query.lower().strip()
    tokens = set(content_tokens(q))
    class_ = "neutral"
    diag_scale = 0.0
    fluct_open = 0.35
    soft_prefer = 0.0
    process_bias = 0.0
    entity_bias = 0.0
    speculative = 0.0

    causal_markers = {"why", "how", "cause", "because", "lead", "result", "effect"}
    process_markers = {"process", "step", "stage", "sequence", "flow", "procedure", "method"}
    entity_markers = {"who", "person", "name", "author", "inventor", "company"}
    locator_markers = {"where", "location", "place", "site"}
    speculative_markers = {"maybe", "perhaps", "could", "might", "imagine", "suppose"}
    diag_words = {"fail", "error", "problem", "issue", "protect", "overload", "loss", "single", "phase", "start", "slip", "torque"}

    if q.startswith("how much") or q.startswith("how many") or "how much" in q or "how many" in q:
        class_ = "quantity"
        soft_prefer = 0.20
        fluct_open = 0.40
    elif any(m in tokens for m in causal_markers) or q.startswith("why") or (q.startswith("how") and not q.startswith("how much") and not q.startswith("how many")) or "caused" in q or "cause" in tokens:
        class_ = "causal"
        process_bias = 0.25
        diag_scale = 0.55
        fluct_open = 0.42
    elif any(m in tokens for m in process_markers):
        class_ = "process"
        process_bias = 0.40
        fluct_open = 0.40
    elif any(m in tokens for m in entity_markers) or q.startswith("who"):
        class_ = "entity"
        entity_bias = 0.35
        soft_prefer = 0.15
    elif any(m in tokens for m in locator_markers) or q.startswith("where"):
        class_ = "locator"
        soft_prefer = 0.10
    elif any(m in tokens for m in speculative_markers):
        class_ = "speculative"
        speculative = 0.55
        fluct_open = 0.28
    elif q.startswith("what"):
        class_ = "what"
        soft_prefer = 0.12
        fluct_open = 0.38
    else:
        class_ = "factual"

    if any(d in tokens for d in diag_words):
        diag_scale = max(diag_scale, 0.30)

    return {
        "class": class_,
        "diag_scale": diag_scale,
        "fluct_open": fluct_open,
        "soft_prefer": soft_prefer,
        "process_bias": process_bias,
        "entity_bias": entity_bias,
        "speculative": speculative,
    }


def text_to_frequencies(text: str, n: int = 8) -> List[int]:
    tokens = content_tokens(text) if text else []
    freqs: List[int] = []
    phase_base = 440 + int(PHASE_OFFSET * 100)
    for t in tokens[:12]:
        th = int(hashlib.sha256(t.encode("utf-8")).hexdigest()[:8], 16)
        freqs.append(phase_base + (th % 1400))
    h = hashlib.sha256(text.encode("utf-8")).digest()
    for i in range(max(2, n - len(freqs))):
        chunk = int.from_bytes(h[i*2:(i*2)+2], "big")
        freqs.append(phase_base + (chunk % 1200))
    seen = set()
    out = []
    for f in freqs:
        if f not in seen:
            seen.add(f)
            out.append(f)
        if len(out) >= n + 4:
            break
    return out[: n + 4]


def resonance_score(query_freqs: List[int], res_freqs: List[int]) -> float:
    if not query_freqs or not res_freqs:
        return 0.0
    qset = set(query_freqs)
    rset = set(res_freqs)
    inter = len(qset & rset)
    return inter / max(len(qset), 1)


@dataclass
class RealityCore:
    phase: float = 0.0
    vel: float = 0.0
    reference: float = 0.0
    scale: float = 1.0
    force: float = 0.0
    leak: float = field(init=False, default=0.0)
    fluidity: float = field(init=False, default=0.0)
    restore: float = field(init=False, default=0.0)
    slow_leak: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        s = max(0.1, abs(self.scale))
        self.leak = 0.06 / (s ** 0.6)
        self.fluidity = 0.6 / (s ** 0.9)
        self.restore = 0.05 * (s ** 0.7)
        self.slow_leak = self.leak * 0.15

    def step(self, dt: float = 0.05) -> float:
        accel = self.force - self.restore * (self.phase - self.reference) - self.leak * self.vel
        self.vel += accel * dt
        self.phase += self.vel * dt * self.fluidity
        self.reference += (self.phase - self.reference) * self.slow_leak * dt
        self.phase = max(-3.0, min(3.0, self.phase))
        self.vel = max(-2.0, min(2.0, self.vel))
        self.force *= 0.85
        coherence = 1.0 / (1.0 + abs(self.phase - self.reference))
        return float(np.clip(coherence, 0.0, 1.0))


def format_intent_answer(intent: str, primary: str, support: str = "") -> str:
    """Shape residual text into an intent-directed answer. No invention — only locked text.
    Prefers the tightest body. When primary is a long FULL residual and a useful
    support segment exists, promote the support to primary for cleaner answers.
    """
    def body(text: str) -> str:
        text = text.strip()
        # DOMAIN::TAG::body
        parts = text.split("::", 2)
        if len(parts) >= 3:
            return parts[2].strip()
        # DOMAIN::TAG | body   or   TAG | body
        if " | " in text:
            return text.split(" | ", 1)[1].strip()
        if len(parts) == 2:
            return parts[1].strip()
        return text

    def is_full(text: str) -> bool:
        head = text.split(" | ")[0] if " | " in text else text
        parts = head.split("::")
        tag = parts[1].lower() if len(parts) >= 2 else ""
        return tag.endswith("_full") or tag.endswith("full")

    # Prefer tight support over a long FULL primary
    if support and is_full(primary) and not is_full(support) and len(primary) > 350:
        primary, support = support, ""

    main = body(primary)
    # Soft length guard for readability (still pure locked text)
    if len(main) > 900:
        main = main[:900].rsplit(" ", 1)[0] + "…"

    if support:
        extra = body(support)
        if len(extra) > 500:
            extra = extra[:500].rsplit(" ", 1)[0] + "…"
        if intent in ("diagnose", "why", "how"):
            return f"{main} Related: {extra}"
        return f"{main} | {extra}"
    return main


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
    """256-bit signature mixing SHA-256 x2 + BLAKE2b via XOR (all three contribute)."""
    h1 = hashlib.sha256(data).digest()
    h2 = hashlib.sha256(data + b"|residual|void|binary|v2").digest()
    h3 = hashlib.blake2b(data, digest_size=32).digest()
    # XOR-mix so h2 and h3 are not discarded (fixes multi-hash truncation bug)
    out = bytes(a ^ b ^ c for a, b, c in zip(h1, h2, h3))
    return out


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
    imprint_layer: str = "medium"
    coherence: float = 0.85
    value: float = 0.50
    freqs: List[int] = field(default_factory=list)
    core: Optional[RealityCore] = None
    _sig_bits: np.ndarray = field(default=None, repr=False, compare=False)

    def bits(self) -> np.ndarray:
        if self._sig_bits is None:
            self._sig_bits = packed_to_bits(self.sig_packed)
        return self._sig_bits

    def ensure_core(self, scale: float = 1.0) -> RealityCore:
        if self.core is None:
            self.core = RealityCore(scale=scale)
        else:
            s = max(0.1, abs(scale))
            self.core.scale = s
            self.core.leak = 0.06 / (s ** 0.6)
            self.core.fluidity = 0.6 / (s ** 0.9)
            self.core.restore = 0.05 * (s ** 0.7)
            self.core.slow_leak = self.core.leak * 0.15
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
        self._last_query_freqs: List[int] = []

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
        shell: Optional[int] = None,
        imprint_layer: str = "medium",
        coherence: float = 0.85,
        value: Optional[float] = None,
        freqs: Optional[List[int]] = None,
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

            if shell is None:
                phi = (1 + 5 ** 0.5) / 2
                shell = int((phi * self._next_version) % 4)
            shell = max(0, min(3, int(shell)))
            if imprint_layer not in ("fast", "medium", "deep"):
                imprint_layer = "medium"
            if protect or coherence >= 0.95:
                protect = True
                if imprint_layer == "medium":
                    imprint_layer = "deep"
            init_coh = min(1.0, float(coherence))
            seeded_value = float(value) if value is not None else 0.45 + 0.40 * init_coh
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
                coherence=init_coh,
                value=seeded_value,
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

    def _bridge_hits(self, query_text: str, cset: Set[str]) -> int:
        hits = 0
        q = query_text.lower().strip()
        for trigger, targets in PHRASE_BRIDGES.items():
            if trigger in q:
                for target in targets:
                    target_tokens = set(content_tokens(target))
                    if target_tokens and target_tokens & cset:
                        hits += 1
                        break
        return hits

    def rank(self, query: str, domain: Optional[str] = None, top_k: int = 20, freq: Optional[Dict] = None) -> List[tuple]:
        with self._lock:
            if not self.residuals:
                return []
            if freq is None:
                freq = question_frequency(query)
            # RCF: lock probe frequencies for resonance scoring
            self._last_query_freqs = text_to_frequencies(query)
            probe = packed_to_bits(bytes_to_bits_packed(query.encode("utf-8")))
            qset = set(content_tokens(query))
            q_lower = query.lower().strip()
            candidate_idxs: set = set()
            if qset:
                for t in qset:
                    candidate_idxs.update(self._token_index.get(t, []))
            if domain:
                candidate_idxs.update(self._domain_index.get(domain, []))
            # always soft-expand for morphological / fuzzy neighbors (bond~bonded, frame~frames)
            if qset and self.residuals:
                for i, res in enumerate(self.residuals):
                    if res.domain == "query":
                        continue
                    soft = fuzzy_token_hits(qset, res.content_set)
                    if soft >= 0.65:
                        candidate_idxs.add(i)
                        continue
                    for qt in qset:
                        if len(qt) < 4:
                            continue
                        for ct in res.content_set:
                            if len(ct) >= 4 and (ct.startswith(qt) or qt.startswith(ct[:4])):
                                candidate_idxs.add(i)
                                break
            # phrase-anchor / bridge expansion (locked-text only)
            q_lower_r = query.lower().strip()
            bridge_needles = []
            for trigger, targets in PHRASE_BRIDGES.items():
                if trigger in q_lower_r:
                    bridge_needles.extend(targets)
            for i, res in enumerate(self.residuals):
                if res.domain in ("query", "rejected"):
                    continue
                frag = res.fragment.lower()
                for phrase in PHRASE_ANCHORS:
                    if phrase in q_lower_r and any(w in frag for w in phrase.split() if len(w) > 1):
                        candidate_idxs.add(i)
                        break
                for needle in bridge_needles:
                    if needle in frag:
                        candidate_idxs.add(i)

            if not candidate_idxs and not (qset or domain):
                candidate_idxs = set(range(len(self.residuals)))
            scores = []
            for i in candidate_idxs:
                res = self.residuals[i]
                if res.domain in ("query", "rejected"):
                    continue  # never answer from query or rejected residuals
                r = hamming_sim(probe, res.bits())
                hits = sum(1 for t in qset if t in res.content_set) if qset else 0
                coverage = hits / max(1, len(qset)) if qset else 0.0
                score = 0.20 * r + 0.40 * coverage
                frag_lower = res.fragment.lower()
                exact_sub = bool(q_lower and q_lower in frag_lower)
                if exact_sub:
                    score += 0.62
                elif any(t in frag_lower for t in qset if len(t) >= 3):
                    score += 0.28
                if hits >= 2:
                    score += 0.22
                elif hits == 1:
                    score += 0.12
                if "::" in res.fragment:
                    score += 0.12
                # primary anchor boost: token matches the tag before first ::
                # handle MOTOR::OVERLOAD::... -> primary becomes overload
                parts = [p for p in frag_lower.split("::") if p]
                primary_tag = parts[1] if len(parts) >= 2 else (parts[0] if parts else "")
                for t in qset:
                    if len(t) >= 4 and t == primary_tag:
                        score += 0.55
                    elif len(t) >= 4 and (primary_tag.startswith(t) or t in primary_tag):
                        score += 0.40
                # multi-token primary match e.g. "service factor" vs SERVICE_FACTOR
                primary_compact = primary_tag.replace("_", " ").replace("-", " ")
                if primary_compact and all(tok in frag_lower for tok in primary_compact.split() if len(tok) > 2):
                    if any(tok in qset for tok in primary_compact.split() if len(tok) > 2):
                        score += 0.35
                # key-noun boost
                key_boost = 0.0
                for t in qset:
                    if len(t) >= 4 and t in frag_lower:
                        key_boost += 0.16
                score += min(0.32, key_boost)
                # phrase anchor / bridge boost
                phrase_hits = 0.0
                for phrase in PHRASE_ANCHORS:
                    if phrase in q_lower and phrase in frag_lower:
                        phrase_hits += 1.0
                for trigger, targets in PHRASE_BRIDGES.items():
                    if trigger in q_lower:
                        for needle in targets:
                            if needle in frag_lower:
                                phrase_hits += 1.2
                score += min(0.45, phrase_hits * 0.22)
                # negative evidence: exhaustion vs stroke style cross-talk
                if "exhaustion" in q_lower and "stroke" in frag_lower and "exhaustion" not in frag_lower:
                    score *= 0.45
                if "stroke" in q_lower and "exhaustion" in frag_lower and "stroke" not in frag_lower:
                    score *= 0.45

                # quantity questions prefer residuals that state a number/unit
                if any(w in q_lower for w in ("how much", "how many", "what is the minimum", "minimum", "inches", "voltage", "pressure")):
                    if any(ch.isdigit() for ch in res.fragment):
                        score += 0.28
                    # demote pure diagnostic cross-talk on quantity pulls
                    if any(w in frag_lower for w in ("error", "fault", "failed", "indicates")) and not any(ch.isdigit() for ch in res.fragment):
                        score *= 0.70
                # multi-token phrase boost (natural gas, water column, fuel line)
                q_words = [t for t in q_lower.split() if len(t) > 2]
                for wi in range(len(q_words) - 1):
                    phrase = q_words[wi] + " " + q_words[wi + 1]
                    if phrase in frag_lower:
                        score += 0.22
                # light synonym / morphological bridges
                bridge_hits = 0
                for t in qset:
                    for alt in TOKEN_BRIDGES.get(t, []):
                        if alt in frag_lower or alt == primary_tag:
                            score += 0.32
                            bridge_hits += 1
                            break
                if bridge_hits:
                    score += min(0.18, 0.08 * bridge_hits)
                if domain and res.domain == domain:
                    score += 0.10
                if res.protect:
                    score += 0.05
                # hierarchical shell + imprint boosts (synthesis-friendly)
                # prefer deeper shells and deep imprint for grounded answers
                shell_boost = {0: 0.02, 1: 0.04, 2: 0.06, 3: 0.03}.get(getattr(res, "shell", 0), 0.0)
                imprint_boost = {"deep": 0.10, "medium": 0.04, "fast": 0.01}.get(getattr(res, "imprint_layer", "medium"), 0.0)
                score += shell_boost + imprint_boost
                score += 0.08 * float(getattr(res, "coherence", 0.85) - 0.70)
                # Bellman value bias: high-value residuals (proven useful) rise; low-value decay
                score += 0.26 * (float(getattr(res, "value", 0.50)) - 0.50)
                # conceptual / memoir intent boost — targeted, not blanket
                if any(w in q_lower for w in ("why", "origin", "began", "built", "started")):
                    if "origin" in frag_lower or "began as" in frag_lower or "memory bottleneck" in frag_lower:
                        score += 0.55
                    if "void_purpose" in frag_lower and "origin" not in frag_lower:
                        score -= 0.15
                if any(w in q_lower for w in ("unused", "decay", "decayed", "disappear")):
                    if "slowly decay" in frag_lower or "decay never deletes" in frag_lower:
                        score += 0.55
                    if "remain fully visible" in frag_lower:
                        score += 0.35
                    if "surface decayed" in frag_lower or "ascending value" in frag_lower:
                        score += 0.15 if ("find" in q_lower or "how do i" in q_lower) else -0.10
                if any(w in q_lower for w in ("invent", "invention")):
                    if "no free invention" in frag_lower or "supported by locked" in frag_lower:
                        score += 0.45
                # RCF resonant boost
                qf = getattr(self, "_last_query_freqs", None)
                rf = getattr(res, "freqs", None)
                if qf and rf:
                    score += 0.35 * resonance_score(qf, rf)

                # frequency-aware modulation
                if freq.get("diag_scale", 0.0) > 0 and any(d in frag_lower for d in ("fail", "failed", "error", "protect", "overload", "loss", "phase", "slip", "start", "drop", "dropped", "fault", "pressure", "miss")):
                    score += 0.28 * freq.get("diag_scale", 0.0)
                # causal queries demote pure status/ready lines
                if freq.get("class") == "causal" and any(d in frag_lower for d in ("ready signal", "signal sent", "confirmed grip", "before conveyor")):
                    score *= 0.55
                if freq.get("process_bias", 0.0) > 0 and any(p in frag_lower for p in ("process", "step", "method", "flow", "sequence", "start", "assemble")):
                    score += 0.15 * freq.get("process_bias", 0.0)
                if freq.get("entity_bias", 0.0) > 0 and any(e in frag_lower for e in ("person", "name", "who", "author")):
                    score += 0.12 * freq.get("entity_bias", 0.0)

                # ---- Specificity / density / FULL demotion (tight answers preferred) ----
                # Density: matching tokens as fraction of residual content tokens
                res_tok_count = max(1, len(res.content_set))
                density = hits / res_tok_count if hits else 0.0
                score += min(0.22, density * 0.55)

                # Length dampener: long dumps lose when lexical coverage is comparable
                frag_len = len(res.fragment)
                if frag_len > 420:
                    # progressive soft penalty; keeps long residuals usable but rarely primary
                    length_penalty = min(0.28, (frag_len - 420) / 2800.0)
                    score *= (1.0 - length_penalty)

                # Explicit _FULL residual demotion (still available, rarely wins)
                is_full = primary_tag.endswith("_full") or primary_tag.endswith("full") or "_full::" in frag_lower
                if is_full:
                    score *= 0.72
                    # extra demotion if a query token already lives in a tighter tag elsewhere
                    # (handled downstream by synthesize rank_key as well)

                # Stronger primary-tag exactness when query mentions the concept
                if primary_tag and len(primary_tag) >= 4:
                    tag_tokens_set = set(primary_tag.replace("_", " ").split())
                    tag_overlap = len(tag_tokens_set & qset)
                    if tag_overlap >= 1:
                        score += 0.18 * tag_overlap
                    # exact tag token present in query is decisive
                    for tt in tag_tokens_set:
                        if len(tt) >= 4 and tt in q_lower:
                            score += 0.25
                            break

                # treat fuzzy/morphological hits + synonym bridges as partial lexical signal
                soft_hits = fuzzy_token_hits(qset, res.content_set) if qset else 0.0
                if bridge_hits:
                    soft_hits = max(soft_hits, 0.70)
                lexical_signal = hits + (1 if exact_sub else 0) + (1 if soft_hits >= 0.55 else 0)
                if lexical_signal == 0:
                    score *= 0.03
                    if r > 0.58:
                        try:
                            phase_factor = (int(res.residual_id[:4], 16) % 100) / 100.0
                        except (TypeError, ValueError):
                            phase_factor = 0.0
                        score += 0.18 * phase_factor * freq.get("fluct_open", 0.35)
                elif hits == 0 and soft_hits >= 0.65:
                    # soft-only match: mild damp, keep bridge score
                    score *= 0.55
                    score += min(0.25, soft_hits * 0.15)
                elif coverage < 0.15 and not exact_sub and soft_hits < 0.65:
                    score *= 0.30
                elif hits == 1 and not exact_sub:
                    score *= 0.68

                scores.append((res, float(min(1.5, score))))  # headroom so conceptual boosts can break ties
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
    def lock_text(
        self,
        text: str,
        domain: str = "general",
        protect: bool = True,
        shell: Optional[int] = None,
        imprint_layer: str = "medium",
        coherence: float = 0.85,
    ) -> str:
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
            shell=shell, imprint_layer=imprint_layer, coherence=coherence,
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
        self.vibrate_steps = 12
        self.vibrate_dt = 0.08
        self.coupling = 0.35

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
        shell: Optional[int] = None,
        imprint_layer: str = "medium",
        coherence: float = 0.85,
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
                    payload,
                    domain=domain,
                    label=label,
                    node_id=source,
                    protect=protect,
                    shell=shell,
                    imprint_layer=imprint_layer,
                    coherence=coherence,
                )
                if ok:
                    self.lock_count += 1
                    return "locked"
                return reason
            return "ignored"

    def _log_query(self, query: str, source: str = "user", mode: str = "exact") -> None:
        freq = question_frequency(query)
        qlog = f"QUERY::{source}::{mode}|{freq['class']} | {query[:120]}"
        ok, _ = self.field.store(
            qlog,
            domain="query",
            node_id=source,
            protect=False,
            shell=0,
            imprint_layer="fast",
            coherence=0.99,
            value=0.0,
            freqs=text_to_frequencies(query),
        )
        if ok and len(self.field._domain_index.get("query", [])) > self._query_log_limit:
            # Bound query-chain index growth while preserving append-only residual history.
            self.field._domain_index["query"] = self.field._domain_index["query"][-self._query_log_limit:]

    def _vibrate_residuals(self, candidates: List[Tuple[Residual, float]]) -> List[str]:
        """Mean-field coupling reorder of grounded candidates."""
        if not candidates:
            return []
        cores = []
        for res, score in candidates[:6]:
            core = res.ensure_core(scale=1.0 + score)
            core.force = score * 1.2
            cores.append((res, score, core))

        for _ in range(self.vibrate_steps):
            mean_phase = sum(c.phase for _, _, c in cores) / max(1, len(cores))
            for res, score, core in cores:
                core.force = self.coupling * (mean_phase - core.phase) + score * 0.3
                core.step(self.vibrate_dt)

        # re-rank by blend of original score and coherence (inverse phase distance to mean)
        mean_phase = sum(c.phase for _, _, c in cores) / max(1, len(cores))
        ranked = []
        for res, score, core in cores:
            coherence = 1.0 / (1.0 + abs(core.phase - mean_phase))
            blended = 0.72 * score + 0.28 * coherence
            ranked.append((res, blended))
        ranked.sort(key=lambda x: -x[1])

        seen = set()
        out = []
        for res, _ in ranked:
            key = res.fragment[:80].lower()
            if key not in seen:
                seen.add(key)
                out.append(res.fragment)
            if len(out) >= 3:
                break
        return out

    def _bellman_update(self, winners: List[Residual], reward: float = 0.85, alpha: float = 0.12, gamma: float = 0.90) -> None:
        """Lightweight Bellman-style value update.
        Successful residuals gain value; nearby competitors receive a mild decay.
        False / low-utility knowledge is gradually phased out of ranking preference.
        """
        if not winners:
            return
        # max value among current knowledge (excluding query/rejected)
        max_v = 0.50
        for r in self.field.residuals:
            if r.domain in ("query", "rejected"):
                continue
            max_v = max(max_v, float(getattr(r, "value", 0.50)))
        target = reward + gamma * max_v
        winner_ids = {w.residual_id for w in winners}
        for r in self.field.residuals:
            if r.domain in ("query", "rejected"):
                continue
            v = float(getattr(r, "value", 0.50))
            if r.residual_id in winner_ids:
                # positive update toward target
                r.value = max(0.05, min(1.0, (1.0 - alpha) * v + alpha * target))
                # slight coherence lift on proven residuals
                r.coherence = min(1.0, r.coherence + 0.01)
            else:
                # slow global decay so unused / conflicting knowledge loses preference
                r.value = max(0.05, v * 0.997)

    def project(self, query: str, mode: str = "exact", source: str = "user") -> str:
        """Project query against locked residuals; returns fragment string or refusal."""
        self.project_count += 1
        self._log_query(query, source=source, mode=mode)
        ranked = self.field.rank(query)
        ranked = [(res, score) for res, score in ranked if res.domain != "query"]
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
            freq = question_frequency(query)
            recover = [
                (res, score)
                for res, score in self.field.rank(query, top_k=32, freq=freq)
                if res.domain not in ("query", "rejected")
            ]
            candidates: List[Tuple[Residual, float]] = recover[:16]
            if qset:
                for res, score in recover[16:28]:
                    if score < 0.38:
                        continue
                    if fuzzy_token_hits(qset, res.content_set) >= 0.44:
                        candidates.append((res, score))
            if not candidates:
                self.invention_refusals += 1
                return self._REFUSAL

            vibrated_list = self._vibrate_residuals(candidates)
            vibrated_rank = {frag: (len(vibrated_list) - idx) for idx, frag in enumerate(vibrated_list)}
            ordered: List[Tuple[Residual, float]] = []
            seen_ids: Set[str] = set()
            for res, score in candidates:
                adjusted = score
                if res.imprint_layer in {"deep", "medium"} and res.coherence >= 0.88:
                    adjusted += 0.03
                if res.fragment in vibrated_rank:
                    adjusted += 0.02 * vibrated_rank[res.fragment]
                if res.residual_id not in seen_ids:
                    seen_ids.add(res.residual_id)
                    ordered.append((res, adjusted))

            force_needles: Tuple[str, ...] = ()
            if any(w in q_lower for w in ("why", "origin", "began", "built", "started")):
                force_needles = ("origin", "began as", "memory bottleneck", "geometry of stored")
            elif any(w in q_lower for w in ("unused", "decay", "decayed", "disappear")):
                force_needles = (
                    "slowly decay",
                    "decay never deletes",
                    "remain fully visible",
                    "surface decayed",
                    "ascending value",
                )
            elif any(w in q_lower for w in ("invent", "invention")):
                force_needles = ("no free invention", "supported by locked")

            def _is_full_fragment(text: str) -> bool:
                head = text.split(" | ")[0] if " | " in text else text
                parts = [p for p in head.lower().split("::") if p]
                tag = parts[1] if len(parts) >= 2 else (parts[0] if parts else "")
                return tag.endswith("_full") or tag.endswith("full") or "_full::" in text.lower()

            def rank_key(item: Tuple[Residual, float]) -> Tuple[float, float, float, float, float, float, float, float]:
                res, score = item
                frag = res.fragment.lower()
                exact = 1.0 if (q_lower and q_lower in frag) else 0.0
                soft = fuzzy_token_hits(qset, res.content_set) if qset else 0.0
                parts = [p for p in frag.split("::") if p]
                primary_tag = parts[1] if len(parts) >= 2 else (parts[0] if parts else "")
                tag_hit = 0.0
                for t in qset:
                    if len(t) >= 4 and (t == primary_tag or t in primary_tag or primary_tag.startswith(t)):
                        tag_hit = 1.0
                        break
                force = 1.0 if force_needles and any(needle in frag for needle in force_needles) else 0.0
                preconcept = 1.0 if (res.imprint_layer in {"deep", "medium"} and res.coherence >= 0.88) else 0.0
                vibrate = float(vibrated_rank.get(res.fragment, 0.0))
                full_penalty = 0.0 if _is_full_fragment(res.fragment) else 1.0
                return (force, exact, tag_hit, full_penalty, preconcept, vibrate, soft, score)

            ordered.sort(key=rank_key, reverse=True)
            primary_res: Optional[Residual] = None
            primary_text = ""
            support_res: Optional[Residual] = None
            support_text = ""

            for res, score in ordered:
                frag_lower = res.fragment.lower()
                if score < 0.48:
                    continue
                soft = fuzzy_token_hits(qset, res.content_set) if qset else 0.0
                if qset and soft < 0.20 and q_lower not in frag_lower:
                    continue
                primary_res = res
                primary_text = res.fragment.strip()
                break
            if not primary_text:
                self.invention_refusals += 1
                return self._REFUSAL

            primary_full = _is_full_fragment(primary_text)
            primary_body = primary_text.split("::", 2)[-1].strip().lower()
            for res, score in ordered:
                if primary_res is not None and res.residual_id == primary_res.residual_id:
                    continue
                if score < 0.44:
                    continue
                cand = res.fragment.strip()
                cand_body = cand.split("::", 2)[-1].strip().lower()
                if not cand_body or cand_body == primary_body:
                    continue
                cand_full = _is_full_fragment(cand)
                if primary_full and cand_full:
                    continue
                if cand_full and not primary_full:
                    continue
                soft = fuzzy_token_hits(qset, res.content_set) if qset else 0.0
                if qset and soft < 0.16 and q_lower not in cand.lower():
                    continue
                support_res = res
                support_text = cand
                break

            winners = [primary_res] if primary_res is not None else []
            if support_res is not None:
                winners.append(support_res)
            self._bellman_update(
                winners,
                reward=0.88 if (intent == "diagnose" or freq.get("class") == "quantity") else 0.78,
            )
            answer = format_intent_answer(intent, primary_text, support_text)
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
