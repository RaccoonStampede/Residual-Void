 or wrong carrier:
                            # keep scanning; the Bellman-fallback aboutness gate
                            # below refuses if nothing is genuinely about target.
            # Pass 2b: MECHANISM intent gate — catches conversational HOW forms
            # that Pass 2 misses (passive voice, subject pronoun, scaffolding
            # verb before the target noun):
            #   "How do you achieve phase lock?"  — target extracted as
            #     "achieve phase lock", aboutness=1 → Pass 2 falls through
            #   "How is phase lock achieved?"     — target "is phase lock achiev",
            #     aboutness=1 → same
            #   "achieve phase lock"              — no HOW prefix at all
            # Strategy: strip all HOW scaffolding with _extract_mechanism_target
            # to get the bare noun phrase, then find any MECHANISM-framed residual
            # whose body contains that phrase.  No aboutness gate: if the
            # mechanism residual explicitly names the target, it answers the query.
            # Falls through (does not refuse) when no MECHANISM residual found.
            if _q_frame == "MECHANISM":
                _mech_tgt = _extract_mechanism_target(query)
                if _mech_tgt:
                    _mech_tgt_l = _mech_tgt.lower()
                    for res, score in ranked:
                        if _frame(res) != "MECHANISM":
                            continue
                        _, _, ev_body = parse_topic_lineage(res.fragment)
                        if _mech_tgt_l in ev_body.lower():
                            _, clean = parse_lineage(res.fragment)
                            return clean
            # Pass 2c: WHY target-aboutness gate.
            # "Why can ego help or hurt?" must return the ego residual, not the
            # empathy residual (both are WHY-framed; soft moral-word bridging
            # causes cross-topic drift without this gate).
            # Strategy: extract the query's subject noun, scan WHY-framed
            # residuals for any whose body mentions that subject, return the
            # first.  Falls through if no WHY residual names the target.
            if _q_frame == "WHY":
                _why_tgt = _extract_why_target(query)
                if _why_tgt:
                    _why_tgt_l = _why_tgt.lower()
                    # Multi-word: accept if ALL head words (len>=4) appear in body.
                    # Single-word: require exact substring match.
                    _why_tgt_words = [w for w in _why_tgt_l.split() if len(w) >= 4]
                    for res, score in ranked:
                        if _frame(res) != "WHY":
                            continue
                        _, _, ev_body = parse_topic_lineage(res.fragment)
                        b_lower = ev_body.lower()
                        if _why_tgt_l in b_lower:
                            _, clean = parse_lineage(res.fragment)
                            return clean
                        if _why_tgt_words and all(w in b_lower for w in _why_tgt_words):
                            _, clean = parse_lineage(res.fragment)
                            return clean
            # Pass 3: WHAT-is definition queries — prefer the residual that
            # *defines* the target over any residual that merely mentions it.
            # Two-pass: definitional body first; non-weak mention as fallback.
            if _is_definition_query(query):
                def_target = _extract_definition_target(query)
                if def_target:
                    _dt3_pat = (
                        re.escape(def_target) + r"s?"
                        if " " not in def_target
                        else re.escape(def_target)
                    )
                    # Pass 3a: body opens with "target is/are …"
                    # Scan the FULL ranked list — in dense same-carrier fields the
                    # definition residual can fall below position 24 in Bellman rank.
                    # Prefer atomic (≤1 interior sentence break) over blob dumps;
                    # blob fallback used only if no atomic match exists anywhere.
                    _def_pat = rf"(?:^|\.\s+)(?:the |your |a |an )?{_dt3_pat}\s+(?:is|are)\b"
                    # Collect ALL definitional candidates instead of returning the
                    # first in Bellman order. Old alternate phrasings accumulate
                    # Bellman value over many rounds and would otherwise permanently
                    # outrank a freshly locked, more precise source residual.
                    # Selection key (descending priority):
                    #   1. atomic body (≤1 interior sentence break)
                    #   2. lead-clause precision — target named at the very start
                    #      of the body beats target buried mid-lead
                    #      + active-engram bonus (the freshest lock in the family)
                    #   3. Bellman-ranked score — tiebreak ONLY; accumulated value
                    #      alone can never override a stronger target match.
                    _def_hits: "List[Tuple[Residual, float, str]]" = []
                    for res, score in ranked:
                        _, _, ev_body = parse_topic_lineage(res.fragment)
                        b_lower = ev_body.lower()
                        if re.search(_def_pat, b_lower[:100]):
                            _def_hits.append((res, score, ev_body))
                    if _def_hits:
                        def _lead_precision(body: str) -> float:
                            b = body.lower()
                            m = re.search(_def_pat, b[:100])
                            if not m:
                                return 0.0
                            pos = m.start()
                            # Target as the opening subject is the most precise
                            # definition; later positions are progressively weaker.
                            if pos == 0:
                                return 3.0
                            if pos <= 30:
                                return 1.5
                            return 0.5
                        _best = max(
                            _def_hits,
                            key=lambda t: (
                                1 if t[2].count(". ") <= 1 else 0,   # atomic first
                                _lead_precision(t[2])
                                + (1.0 if t[0].active else 0.0),      # fresh lock wins
                                t[1],                                 # Bellman tiebreak
                            ),
                        )
                        _, clean = parse_lineage(_best[0].fragment)
                        return clean
                    # Pass 3b: target in body, not buried in a list/attribute clause
                    for res, score in ranked:
                        _, _, ev_body = parse_topic_lineage(res.fragment)
                        b_lower = ev_body.lower()
                        if score >= 0.25 and re.search(rf"\b{_dt3_pat}\b", b_lower):
                            _weak3 = bool(re.search(
                                rf"(?:"
                                rf",\s*{_dt3_pat}"
                                rf"|{_dt3_pat}\s*,"
                                rf"|\b(?:carries?|includes?|including|contains?)\b[^.]*\b{_dt3_pat}\b"
                                rf")",
                                b_lower[:200],
                            ))
                            if not _weak3:
                                _, clean = parse_lineage(res.fragment)
                                return clean
            # Pass 4: CONDITION queries — full ranked scan, atomic-first.
            # Same-carrier dump residuals (boat/storm with broad token coverage)
            # can outrank the correctly-framed IF/without residual in dense fields;
            # scanning the full list and preferring atomic bodies prevents this.
            if _is_condition_query(query):
                _cond_blob: "Residual | None" = None
                for res, score in ranked:
                    _, _, ev_body = parse_topic_lineage(res.fragment)
                    if _frame(res) == "CONDITION":
                        if fuzzy_token_hits(qset, res.content_set) >= 0.15:
                            if ev_body.count(". ") <= 1:   # atomic
                                _, clean = parse_lineage(res.fragment)
                                return clean
                            elif _cond_blob is None:
                                _cond_blob = res
                if _cond_blob is not None:
                    _, clean = parse_lineage(_cond_blob.fragment)
                    return clean
            # Off-domain action refuse: queries that request off-field
            # generative tasks (write, code, joke, draw, generate, invent)
            # must not be satisfied by weak Bellman token overlap.
            # "Write python code" shares "lock" with mechanism residuals but
            # is clearly outside the field ontology.
            _OFF_DOMAIN: frozenset = frozenset({
                "write", "code", "joke", "draw", "generate", "invent",
                "create", "make", "tell", "sing", "translate", "summarise",
            })
            _q_first = q_lower.split()[0] if q_lower else ""
            if _q_first in _OFF_DOMAIN:
                self.invention_refusals += 1
                return self._REFUSAL
            # Fallback: top Bellman match with token-hit threshold.
            top_res, top_score = ranked[0]
            hits = sum(1 for t in qset if t in top_res.content_set) if qset else 0
            exact_sub = bool(q_lower and q_lower in top_res.fragment.lower())
            if hits == 0 and not exact_sub:
                self.invention_refusals += 1
                return self._REFUSAL
            if top_score < 0.62 and hits < 2 and not exact_sub:
                self.invention_refusals += 1
                return self._REFUSAL
            # Off-target gate: query has ≥3 distinctive terms but zero evidence
            # match → selected only by Bellman weight on a shared entity token.
            # Prefer empty over a wrong related residual.
            _, _, _et_body = parse_topic_lineage(top_res.fragment)
            _et_ev = _evidence_score(query, _et_body)
            if _et_ev == 0.0:
                _et_q_words = [w.strip("?.,!") for w in query.lower().split()
                               if len(w) > 3 and w.strip("?.,!") not in _EVIDENCE_STOP]
                if len(_et_q_words) >= 3:
                    self.invention_refusals += 1
                    return self._REFUSAL
            # Carrier-aboutness gate (Bellman fallback, MECHANISM frame only):
            # within the frame-gated set, the top-Bellman residual must have the
            # query's noun target as its primary subject.  If it doesn't, swap
            # in the best-ranked residual that does; if none exists, refuse —
            # a wrong-carrier HOW residual must never win on Bellman weight.
            # DEFINITION queries are handled by Pass 3 (_extract_definition_target)
            # and CONDITION queries by Pass 4; both bypass this gate.
            if _q_frame == "MECHANISM":
                _ab_stems = _extract_action_stems(query)
                _ab_target = _extract_carrier_target(query, _ab_stems)
                if _ab_target:
                    _, _, _ab_top_body = parse_topic_lineage(top_res.fragment)
                    _ab_top = _carrier_aboutness(_ab_target, _ab_top_body)
                    if _ab_top < 2:
                        # Find the best-ranked candidate with the target as its
                        # primary subject (grade 2). Grade 1 (incidental
                        # possessive/prepositional mention) is NOT sufficient to
                        # answer a target-specific MECHANISM query.
                        _ab_swap: "Optional[Tuple[Residual, float]]" = None
                        for _ab_res, _ab_score in ranked:
                            if _ab_score < 0.30:
                                break
                            _, _, _ab_body = parse_topic_lineage(_ab_res.fragment)
                            if _carrier_aboutness(_ab_target, _ab_body) == 2:
                                _ab_swap = (_ab_res, _ab_score)
                                break
                        if _ab_swap is not None:
                            top_res, top_score = _ab_swap
                        else:
                            # No residual anywhere has this carrier as its primary
                            # subject — refuse rather than let a wrong-carrier or
                            # incidental-mention body win on Bellman weight.
                            self.invention_refusals += 1
                            return self._REFUSAL
            # Active-engram verbatim guarantee: if the fallback winner is a latent
            # cousin, swap it for the active sibling from the same family when one
            # exists with a sufficient score. This prevents Bellman-frozen alternates
            # from permanently drifting into the recall slot for their family.
            if top_res.family and not top_res.active:
                for res2, score2 in ranked[:24]:
                    if res2.family == top_res.family and res2.active and score2 >= 0.40:
                        top_res = res2
                        break
            _, clean = parse_lineage(top_res.fragment)
            return clean
        if mode == "synthesize":
            intent_cell = classify_intent_cell(query)
            intent = intent_cell.primary
            lin_intent = detect_intent(query)
            query_topics = detect_topics(query)
            freq = question_frequency(query)
            recover = [
                (res, score)
                for res, score in self.field.rank(
                    query, top_k=64, freq=freq, layer="shadow"
                )
                if res.domain not in ("query", "rejected") and not self._is_json_leak(res.fragment)
            ]
            candidates: List[Tuple[Residual, float]] = recover[:32]
            if qset:
                for res, score in recover[32:]:
                    if score < 0.38:
                        continue
                    if fuzzy_token_hits(qset, res.content_set) >= 0.44:
                        candidates.append((res, score))
            if not candidates:
                self.invention_refusals += 1
                return self._REFUSAL

            # Semantic rescue: for intent-specific queries the correct answer
            # may rank below position 16 purely on Bellman magnitude (e.g. a
            # freshly locked definition losing to a mature incidental mention).
            # Scan all of `recover` (up to top_k=32, which covers a corpus of
            # 17+ residuals completely) and add the best semantic match to
            # candidates if it is missing.
            _cand_ids: Set[str] = {r.residual_id for r, _ in candidates}
            if _is_definition_query(query):
                _rsc_tgt = _extract_definition_target(query)
                if _rsc_tgt:
                    _rsc_pat = (
                        re.escape(_rsc_tgt) + r"s?"
                        if " " not in _rsc_tgt else re.escape(_rsc_tgt)
                    )
                    for _rr, _rs in recover:
                        if _rr.residual_id in _cand_ids:
                            continue
                        _, _, _rb = parse_topic_lineage(_rr.fragment)
                        if re.search(
                            rf"(?:^|\.\s+)(?:the |your |a |an )?{_rsc_pat}\s+(?:is|are)\b",
                            _rb.lower()[:100],
                        ):
                            candidates.append((_rr, _rs))
                            break
            elif lin_intent == "WHY":
                _rsc_why = _extract_why_target(query)
                if _rsc_why:
                    _rsc_why_stem = (
                        _rsc_why.rstrip("s") if len(_rsc_why) > 4 else _rsc_why
                    )
                    _rsc_why_pat = re.escape(_rsc_why_stem) + r"\w*"
                    for _rr, _rs in recover:
                        if _rr.residual_id in _cand_ids:
                            continue
                        _, _, _rb = parse_topic_lineage(_rr.fragment)
                        _rb_l = _rb.lower()
                        _tpos = _rb_l.find(_rsc_why_stem[:5])
                        if _tpos != -1 and _tpos <= 25 and re.search(
                            rf"\b{_rsc_why_pat}\b", _rb_l[:120]
                        ):
                            candidates.append((_rr, _rs))
                            break
            elif _is_condition_query(query):
                _rsc_abs = re.search(
                    r"(?:if there (?:is|are) no|without|if not)\s+(\w+)",
                    query.lower(),
                )
                if _rsc_abs and len(_rsc_abs.group(1)) >= 5:
                    _rsc_noun = _rsc_abs.group(1)
                    for _rr, _rs in recover:
                        if _rr.residual_id in _cand_ids:
                            continue
                        _, _, _rb = parse_topic_lineage(_rr.fragment)
                        if re.search(
                            rf"without {_rsc_noun}|no {_rsc_noun}\b|{_rsc_noun} cannot\b",
                            _rb.lower(),
                        ):
                            candidates.append((_rr, _rs))
                            break

            # ── Harness + HyperSeed scope (Shadow-only) ─────────────────────
            # Stage A: no opinionated rank feature is allowed to rescue an
            # ungrounded shadow. Target identity is re-applied here because the
            # semantic-rescue scan above intentionally starts from the wider set.
            if not _is_multi_body:
                _sq_target = _extract_synthesize_query_target(query)
                if _sq_target:
                    _targeted = [
                        (r, s) for r, s in candidates
                        if _residual_matches_target(_sq_target, r)
                    ]
                    if _targeted:
                        candidates = _targeted
                    else:
                        self.invention_refusals += 1
                        return self._REFUSAL

            _ground_terms = self._exact_terms(query)

            def _grounding_strength(residual: Residual) -> float:
                _, _, ground_body = parse_topic_lineage(residual.fragment)
                exact_hits = self._hard_term_hits(_ground_terms, residual)
                coverage = exact_hits / max(1, len(_ground_terms))
                evidence = _evidence_score(query, ground_body) / 1.5
                soft = fuzzy_token_hits(qset, residual.content_set) if qset else 0.0
                return max(coverage, evidence, soft)

            grounded = [
                (residual, score)
                for residual, score in candidates
                if _grounding_strength(residual) > 0.0
            ]
            if not grounded:
                self.invention_refusals += 1
                return self._REFUSAL
            candidates = grounded

            # Select the queried universe by evidence before mass is considered.
            # This prevents a heavy but unrelated seed from capturing the query.
            _seed_grounding: Dict[str, float] = {}
            _seed_mass: Dict[str, float] = {}
            for _seed_res, _ in candidates:
                _seed_grounding[_seed_res.seed_identity] = max(
                    _seed_grounding.get(_seed_res.seed_identity, 0.0),
                    _grounding_strength(_seed_res),
                )
                _seed_mass[_seed_res.seed_identity] = max(
                    _seed_mass.get(_seed_res.seed_identity, 0.0),
                    _seed_res.seed_mass,
                )
            _primary_seed = max(
                _seed_grounding,
                key=lambda seed_id: (
                    _seed_grounding[seed_id],
                    1.0 + min(
                        0.20,
                        0.05 * math.log1p(max(0.0, _seed_mass[seed_id])),
                    ),
                    seed_id,
                ),
            )
            _eligible_seed_ids: Set[str] = {_primary_seed}
            _cross_seed_intent = _query_frame(query) in {"COMPARE", "RELATE"}
            if _cross_seed_intent:
                _eligible_seed_ids.update(_seed_grounding)
            else:
                _query_freqs = text_to_frequencies(query)
                for _seed_res, _ in candidates:
                    if _seed_res.seed_identity == _primary_seed:
                        continue
                    if (
                        resonance_score(_query_freqs, _seed_res.freqs)
                        >= self.cross_seed_resonance_threshold
                    ):
                        _eligible_seed_ids.add(_seed_res.seed_identity)
            candidates = [
                (residual, score)
                for residual, score in candidates
                if residual.seed_identity in _eligible_seed_ids
            ]
            # ── End harness + HyperSeed scope ───────────────────────────────

            # ── Hard frame gate (synthesize) ─────────────────────────────────
            # Same rule as exact path: wrong-frame residuals are ineligible
            # when a correctly-framed candidate exists.
            #
            # Synthesize extension (change order §3): after narrowing to
            # frame-matched primaries, allow up to ONE sibling from the same
            # residual family whose frame is not a hard mismatch — this lets
            # synthesize surface a compatible supporting residual (e.g. the
            # WHY alongside the DEFINITION) without letting wrong-frame
            # same-carrier residuals claim the primary slot.
            _sq_frame = _query_frame(query)
            if _sq_frame != "GENERAL":
                _sf_matched = [
                    (r, s) for r, s in candidates
                    if _frame(r) == _sq_frame
                ]
                if _sf_matched:
                    _sf_families = {r.family for r, _ in _sf_matched if r.family}
                    # Hard-mismatch frames that must never appear as primary
                    _hard_mismatch = {
                        "DEFINITION": {"MECHANISM"},
                        "MECHANISM":  {"CONDITION"},
                        "WHY":        {"MECHANISM"},
                        "CONDITION":  {"MECHANISM"},
                    }.get(_sq_frame, set())
                    _sf_siblings = [
                        (r, s) for r, s in candidates
                        if (r, s) not in _sf_matched
                        and r.family in _sf_families
                        and _frame(r) not in _hard_mismatch
                    ]
                    candidates = _sf_matched + _sf_siblings[:1]
            # ── End frame gate ───────────────────────────────────────────────

            # ── Synthesize multi-residual: COMPARE composition + STEPS assembly ─
            # Mirror of the exact-path multi-residual block for the two intents
            # that need it most.  Returns List[str] directly so merged.py builds
            # the multi-item results list.
            if _sq_frame == "COMPARE":
                _sm_hits: "List[str]" = []
                _sm_seen: "Set[str]" = set()
                # Pass 1: explicit COMPARE / RELATION candidates
                for _sr, _ss in candidates:
                    if _frame(_sr) in ("COMPARE", "RELATION"):
                        if fuzzy_token_hits(qset, _sr.content_set) >= 0.08:
                            _, _sc = parse_lineage(_sr.fragment)
                            _sk = _sc[:80].lower()
                            if _sk not in _sm_seen:
                                _sm_seen.add(_sk)
                                _sm_hits.append(_sc)
                    if len(_sm_hits) >= 2:
                        break
                # Pass 2: compose from target-A def + target-B def
                if len(_sm_hits) < 2:
                    _sctgts = _extract_compare_targets(query)
                    _sby_tgt: "Dict[str, str]" = {}
                    for _sr, _ss in candidates:
                        if _frame(_sr) not in ("DEFINITION", "FACT"):
                            continue
                        _, _, _srb = parse_topic_lineage(_sr.fragment)
                        _srbl = _srb.lower()
                        for _stgt in _sctgts:
                            if _stgt.lower() not in _sby_tgt and _stgt.lower() in _srbl:
                                _, _sc = parse_lineage(_sr.fragment)
                                _sk = _sc[:80].lower()
                                if _sk not in _sm_seen:
                                    _sm_seen.add(_sk)
                                    _sby_tgt[_stgt.lower()] = _sc
                    for _sv in list(_sby_tgt.values()):
                        if _sv not in _sm_hits:
                            _sm_hits.append(_sv)
                        if len(_sm_hits) >= 2:
                            break
                if _sm_hits:
                    self._bellman_update(
                        [r for r, _ in candidates if parse_lineage(r.fragment)[1] in _sm_hits[:2]],
                        reward=0.78,
                    )
                    return _sm_hits
            elif _sq_frame == "STEPS":
                # Same root-cause fix as exact path: family-prefix scope.
                _STEP_NUM_RE_S = re.compile(r"^step\s*(\d+)", re.IGNORECASE)
                _FAMSUFFIX_RE_S = re.compile(r"-\d+$")
                _ss_anchor_prefix: "Optional[str]" = None
                _ss_anchor_source: "Optional[str]" = None
                for _sr, _ in candidates:
                    _, _, _assb = parse_topic_lineage(_sr.fragment)
                    if _frame(_sr) == "STEP" or _STEP_NUM_RE_S.match(_assb.strip()):
                        same_source_steps = sum(
                            1
                            for candidate in self.field.residuals
                            if (
                                candidate.layer in {"shadow", "legacy"}
                                and candidate.source_id == _sr.source_id
                                and _frame(candidate) == "STEP"
                            )
                        )
                        if same_source_steps > 1:
                            _ss_anchor_source = _sr.source_id
                        if _sr.family:
                            _ss_anchor_prefix = _FAMSUFFIX_RE_S.sub("", _sr.family)
                        break
                _ss_items: "List[Tuple[int, str]]" = []
                _ss_seen: "Set[str]" = set()
                for _sr in self.field.residuals:
                    if (
                        _sr.layer not in {"shadow", "legacy"}
                        or _sr.domain in ("query", "rejected")
                        or _sr.seed_identity not in _eligible_seed_ids
                    ):
                        continue
                    _, _, _ssb = parse_topic_lineage(_sr.fragment)
                    _ssm = _STEP_NUM_RE_S.match(_ssb.strip())
                    if _frame(_sr) != "STEP" and not _ssm:
                        continue
                    if _ss_anchor_source:
                        if _sr.source_id != _ss_anchor_source:
                            continue
                    elif _ss_anchor_prefix:
                        _sr_prefix = _FAMSUFFIX_RE_S.sub("", _sr.family or "")
                        if _sr_prefix != _ss_anchor_prefix:
                            continue
                    else:
                        _sfrag_l = _sr.fragment.lower()
                        if not any(t in _sfrag_l for t in qset if len(t) >= 3):
                            continue
                    _snum = int(_ssm.group(1)) if _ssm else 999
                    _, _sc = parse_lineage(_sr.fragment)
                    _sk = _sc[:80].lower()
                    if _sk not in _ss_seen:
                        _ss_seen.add(_sk)
                        _ss_items.append((_snum, _sc))
                _ss_items.sort(key=lambda x: x[0])
                _ss_hits = [_b for _, _b in _ss_items]
                if _ss_hits:
                    return _ss_hits
            elif _sq_frame in ("LIST", "SUMMARIZE", "RELATE"):
                # Mirror of the exact-path LIST/SUMMARIZE/RELATE assembly.
                # Residuals carry frames like LIST_ITEM, never "LIST", so the
                # frame gate above never narrows candidates for these intents —
                # collect the frame-allowed matches here and return List[str].
                _sl_frame_allowed: "Optional[Set[str]]" = {
                    "LIST":      {"LIST_ITEM"},
                    "SUMMARIZE": None,
                    "RELATE":    {"RELATION", "DEFINITION", "MECHANISM"},
                }[_sq_frame]
                _sl_max_items = 2 if _sq_frame == "RELATE" else 5
                _sl_hits: "List[str]" = []
                _sl_seen: "Set[str]" = set()
                for _sr, _ss in candidates:
                    if fuzzy_token_hits(qset, _sr.content_set) < 0.10:
                        continue
                    if _sl_frame_allowed is not None and _frame(_sr) not in _sl_frame_allowed:
                        continue
                    _, _sc = parse_lineage(_sr.fragment)
                    _sk = _sc[:80].lower()
                    if _sk in _sl_seen:
                        continue
                    _sl_seen.add(_sk)
                    _sl_hits.append(_sc)
                    if len(_sl_hits) >= _sl_max_items:
                        break
                if _sl_hits:
                    return _sl_hits
                # No frame-matched residuals → fall through to single-body passes
            # ── End synthesize multi-residual ─────────────────────────────────

            ordered: List[Tuple[Residual, float]] = []
            seen_ids: Set[str] = set()
            for res, score in candidates:
                adjusted = score
                if res.imprint_layer in {"deep", "medium"} and res.coherence >= 0.88:
                    adjusted += 0.03
                # Evidence score: content match is a first-class signal.
                res_topic, res_lineage, ev_body = parse_topic_lineage(res.fragment)
                ev = _evidence_score(query, ev_body)
                adjusted += ev * 1.4   # exact phrase (1.5) → +2.1; strong overlap → +1.4

                # Auto-derive topic for untagged residuals so raw material competes fairly.
                if res_topic is None:
                    res_topic = _auto_topic_from_body(ev_body)

                # Topic-bound lineage boost: parent topic must match before lineage fires.
                lineage_match = (res_lineage == lin_intent and lin_intent != "GENERAL")
                if query_topics:
                    topic_match = (res_topic in query_topics)
                    if topic_match and lineage_match:
                        adjusted += 2.0   # strongest: correct parent + correct lineage
                    elif topic_match:
                        adjusted += 0.8   # strong: correct parent, any lineage
                    elif res_topic is not None and not topic_match:
                        adjusted -= 0.6   # penalty: explicit wrong parent topic
                    # cross-topic lineage match gets no boost — cannot beat same-topic
                else:
                    # No topic context — fall back to lineage-only (existing behaviour)
                    if lineage_match:
                        adjusted += 1.5
                    elif res_lineage is not None:
                        adjusted -= 0.3
                # Intent Cell preference runs only after relevance, target,
                # grounding, seed, and frame eligibility have already admitted
                # this Shadow. It cannot make an ineligible residual relevant.
                adjusted += 0.65 * _intent_branch_strength(intent_cell, res)
                # Destructive: label/title fragments never beat a substantive residual.
                # Applied universally before intent-specific scoring.
                if _is_label_fragment(ev_body):
                    # Bare titles remain destructive, but a compact operational
                    # status sentence can be verb-less and still carry grounded
                    # content (for example a CMD tag with five status terms).
                    adjusted -= 2.5 if len(content_tokens(ev_body)) <= 3 else 0.4

                # Intent-specific role preference + subject-anchor scoring.
                #
                # Priority order (checked top-to-bottom; first match wins the role branch):
                #   1. Condition query  → prefer CONDITION, demote MECHANISM
                #   2. Definition query → WHAT subject-anchor (definitional > lead > body > off-topic)
                #   3. WHY query        → subject-anchor on explanatory target
                #   4. HOW / action    → action-target coupling check, synonym expansion
                #
                # Core rule: recall the memory *about* the target, not every memory
                # that merely contains the target word.
                role = _frame(res)
                if _is_condition_query(query):
                    # "What happens if …", "if not …", "without …": want CONDITION bodies.
                    if role == "CONDITION":
                        adjusted += 6.0   # frame match — large enough to beat Bellman magnitude
                    elif role == "MECHANISM":
                        adjusted -= 8.0   # frame mismatch — hard demote
                elif _is_definition_query(query):
                    # "What is X" / "What are X": the residual that *defines* X must
                    # decisively beat any residual that only *mentions* X.
                    def_target = _extract_definition_target(query)
                    if def_target:
                        b_lower = ev_body.lower()
                        # Word-boundary pattern: exact + optional trailing 's' for plurals.
                        if " " not in def_target:
                            t_pat = re.escape(def_target) + r"s?"
                        else:
                            t_pat = re.escape(def_target)
                        # Definitional pattern: target is primary subject of an identity clause
                        # at the very start of the body — excludes conditional openers
                        # like "When too many boats are …".
                        definitional = bool(re.search(
                            rf"(?:^|\.\s+)(?:the |your |a |an )?{t_pat}\s+(?:is|are)\b",
                            b_lower[:100],
                        ))
                        in_lead = bool(re.search(rf"\b{t_pat}\b", b_lower[:140]))
                        in_body = bool(re.search(rf"\b{t_pat}\b", b_lower))
                        # Detect weak-mention context: target listed as an
                        # attribute/object of another subject ("carries X",
                        # "including X") or buried in a comma-separated enumeration.
                        _weak_ctx = in_lead and bool(re.search(
                            rf"(?:"
                            rf"\b(?:carries?|includes?|including|contains?|encodes?|stores?)\b[^.{{0,60}}]\b{t_pat}\b"
                            rf"|,\s*{t_pat}"
                            rf"|{t_pat}\s*,"
                            rf")",
                            b_lower[:200],
                        ))
                        if definitional:
                            adjusted += 4.0   # body IS the definition of target
                        elif in_lead and not _weak_ctx:
                            adjusted += 2.0   # target is primary lead subject
                        elif in_body:
                            adjusted += 0.5   # incidental or list mention
                        else:
                            adjusted -= 2.0   # off-topic: hard demote
                        # Foreign subject penalty: if this residual opens with a
                        # definitional clause for a *different* entity, it is about
                        # something else — demote even if it mentions the target.
                        if not definitional:
                            _fsm = re.match(
                                r'^(?:the |a |an |your )?(.+?)\s+(?:is|are)\b',
                                b_lower[:80],
                            )
                            if _fsm:
                                _fsubj = _fsm.group(1).strip()
                                if len(_fsubj) >= 3:
                                    _t_words = set(def_target.split())
                                    _s_words = set(_fsubj.split())
                                    if not (_t_words & _s_words):
                                        adjusted -= 2.5  # defines something else
                    # Frame preference: same target + right frame must beat
                    # same target + wrong frame. Bonuses/penalties must exceed
                    # typical Bellman magnitude differences in a trained field.
                    if role == "DEFINITION":
                        adjusted += 6.0   # frame match — WHAT wants a definition
                    elif role == "MECHANISM":
                        # Hard-demote MECHANISM for DEFINITION queries — UNLESS
                        # this MECHANISM residual is itself *about* the target
                        # (its lead subject IS the definition target, meaning
                        # the field has no DEFINITION-framed body for it and the
                        # MECHANISM body is the best available answer).
                        # "What is the fitness gate?" + FITNESS_GATE_MECHANISM
                        # body "Fitness gate selects…" → lead matches → keep.
                        _mech_lead_ok = bool(re.match(
                            rf"^(?:the |a |an )?{t_pat}\b",
                            ev_body.lower()[:80],
                        ))
                        if not _mech_lead_ok:
                            adjusted -= 8.0  # frame mismatch, wrong carrier → demote
                elif lin_intent == "WHY":
                    # WHY queries: prefer residuals that *explain* the target.
                    # A residual that merely mentions the subject incidentally is penalised.
                    why_target = _extract_why_target(query)
                    if why_target:
                        b_lower = ev_body.lower()
                        if " " not in why_target:
                            t_pat = re.escape(why_target.rstrip("s") if len(why_target) > 4 else why_target) + r"\w*"
                        else:
                            t_pat = re.escape(why_target)
                        in_lead  = bool(re.search(rf"\b{t_pat}\b", b_lower[:120]))
                        has_target = bool(re.search(rf"\b{t_pat}\b", b_lower))
                        t_pos = b_lower.find(why_target[:5])   # approximate position
                        if in_lead and t_pos <= 20:
                            adjusted += 3.0   # target IS the explanatory subject
                        elif in_lead:
                            adjusted += 1.5   # target in lead but not primary subject
                        elif has_target:
                            adjusted += 0.3   # incidental mention
                        else:
                            adjusted -= 1.5   # target absent — off-topic
                    # Frame mismatch penalty for WHY: a MECHANISM body answers
                    # "how" not "why" — demote it hard relative to an explanatory frame.
                    if role == "MECHANISM":
                        adjusted -= 6.0
                elif lin_intent == "HOW" or _is_action_query(query):
                    # HOW / action / WHEN queries: want MECHANISM bodies where
                    # the action verb operates *on* the query target — not just
                    # any body that contains the action somewhere.
                    b_ev_lower = ev_body.lower()
                    action_stems = _extract_action_stems(query)

                    # Verb match: literal stem OR synonym from _ACTION_SYNONYMS.
                    verb_match = any(stem in b_ev_lower for stem in action_stems)
                    if not verb_match and action_stems:
                        for _stem in action_stems:
                            for _syn in _ACTION_SYNONYMS.get(_stem, []):
                                if _syn in b_ev_lower:
                                    verb_match = True
                                    break
                            if verb_match:
                                break

                    # Action-target coupling: the matched verb must appear near
                    # the noun target (within ~80 chars), preventing a body that
                    # suppresses "the storm" from winning "suppress ghost tax".
                    how_target = _extract_how_target(query, action_stems)
                    action_coupled = False
                    if how_target and verb_match:
                        t_pat_ht = re.escape(how_target)
                        # Collect every verb/synonym match position and check proximity.
                        _match_terms: List[str] = list(action_stems)
                        for _stem in action_stems:
                            _match_terms.extend(_ACTION_SYNONYMS.get(_stem, []))
                        for _term in _match_terms:
                            for _m in re.finditer(re.escape(_term), b_ev_lower):
                                region = b_ev_lower[max(0, _m.start() - 30): _m.end() + 80]
                                if re.search(rf"\b{t_pat_ht}\b", region):
                                    action_coupled = True
                                    break
                            if action_coupled:
                                break

                    if action_coupled:
                        adjusted += 3.5   # verb operates on the correct target — decisive
                    elif verb_match:
                        adjusted += 2.0   # verb present but aimed at a different target
                    elif len(ev_body.strip()) < 80 or not action_stems:
                        pass              # very short body: no penalty
                    else:
                        adjusted -= 0.5  # demote noun-only bodies on action queries

                    if role == "MECHANISM":
                        adjusted += 0.8
                    elif role == "CONDITION":
                        adjusted -= 0.8
                    # Linked-term synonym bridge (ghost tax ↔ floor/gamma, etc.)
                    adjusted += _linked_term_evidence(query, ev_body)
                # Active-engram bonus: the preferred recall engram for its family
                # gets a scoring advantage over latent cousins.
                if res.active:
                    adjusted += 0.25
                # Stage B: post-harness inertia and controlled Voice energy.
                # Mass is deliberately bounded and only acts inside the already
                # grounded/eligible seed set, so it cannot make an unrelated seed
                # relevant or override a hard exact match.
                _intent_gate = 1.0
                if res.seed_intent:
                    _intent_terms = {
                        intent.lower(),
                        lin_intent.lower(),
                        _sq_frame.lower(),
                    }
                    _intent_gate = (
                        1.05
                        if res.seed_intent.lower() in _intent_terms
                        else 0.94
                    )
                _mass_boost = 1.0 + min(
                    0.20,
                    0.05 * math.log1p(max(0.0, res.seed_mass)),
                )
                adjusted *= _intent_gate * _mass_boost
                if self.boost_enabled:
                    # Deterministic bounded oscillation: variability without
                    # randomness or invented text.
                    _phase = int(res.residual_id[:8], 16) / float(0xFFFFFFFF)
                    _oscillation = (
                        (_phase - 0.5)
                        * 2.0
                        * self.boost_sigma
                        * self.boost_beta
                        * min(1.0, self.harness_gamma / self.boost_gamma)
                    )
                    adjusted += _oscillation
                if res.residual_id not in seen_ids:
                    seen_ids.add(res.residual_id)
                    ordered.append((res, adjusted))

            # Memory governance penalty pass — applied after full scoring so the
            # active_engram_bonus above is visible when computing family bests.
            #
            # interference_penalty  (−0.20): latent variant loses to active sibling.
            # off_family_penalty    (−0.15): residual from a non-queried family that
            #   already has a strong active engram recalled (score ≥ 0.55).
            _family_active_best: Dict[str, float] = {}
            for _r, _adj in ordered:
                if _r.active and _r.family:
                    if _adj > _family_active_best.get(_r.family, -999.0):
                        _family_active_best[_r.family] = _adj
            # Query family tokens — family slugs overlap with query tokens
            _q_family_parts: Set[str] = set()
            for _tok in qset:
                _q_family_parts.add(_tok)
                for _part in _tok.split("-"):
                    if len(_part) >= 3:
                        _q_family_parts.add(_part)

            def _family_overlaps_query(fam: str) -> bool:
                if not fam:
                    return True  # no family key → no off-family penalty
                return any(p in _q_family_parts or fam in _q_family_parts
                           for p in fam.split("-"))

            ordered = [
                (
                    _r,
                    _adj
                    - (0.20 if (not _r.active and _r.family and
                                _family_active_best.get(_r.family, -999.0) > _adj) else 0.0)
                    - (0.15 if (_r.family and not _family_overlaps_query(_r.family) and
                                _family_active_best.get(_r.family, -999.0) >= 0.55) else 0.0),
                )
                for _r, _adj in ordered
            ]

            # Carrier-wave pass: drive top candidates against query reference (+1.0).
            # Wanted modes phase-lock → boost + motion reward; unwanted modes cancel.
            # Applied after the full scoring loop so carrier uses real net scores.
            carrier_boosts, in_phase_set = self._vibrate_residuals(ordered[:6])
            ordered = [
                (res, adj + carrier_boosts.get(res.residual_id, 0.0))
                for res, adj in ordered
            ]
            # Optional Pure-Harness phase signal: raw offsets are centered, while
            # the applied score preserves the primary-admission floor. It runs only
            # for candidates that already satisfy the unmodified cutoff and evidence.
            ordered = self._apply_pure_harness_phase_signal(
                ordered,
                qset,
                q_lower,
            )

            # WHAT-query definitional override: after all scoring (including
            # carrier-wave), if any candidate opens with "target is/are …" it is
            # the authoritative definition and must rank #1 regardless of how much
            # Bellman magnitude has accumulated on an incidental-mention residual.
            if _is_definition_query(query):
                _def_tgt = _extract_definition_target(query)
                if _def_tgt:
                    _def_tpat = (
                        re.escape(_def_tgt) + r"s?"
                        if " " not in _def_tgt
                        else re.escape(_def_tgt)
                    )
                    _max_adj = max((a for _, a in ordered), default=0.0)
                    for _di, (_dr, _da) in enumerate(ordered):
                        _, _, _db = parse_topic_lineage(_dr.fragment)
                        if re.search(
                            rf"(?:^|\.\s+)(?:the |your |a |an )?{_def_tpat}\s+(?:is|are)\b",
                            _db.lower()[:100],
                        ):
                            ordered[_di] = (_dr, _max_adj + 100.0)
                            break   # first definitional candidate wins
            elif lin_intent == "WHY":
                # WHY override: the residual where the subject target appears
                # at the very start (position ≤ 20) is the explanatory answer;
                # promote it above any incidental mention.
                _why_tgt_o = _extract_why_target(query)
                if _why_tgt_o:
                    _why_stem_o = (
                        _why_tgt_o.rstrip("s") if len(_why_tgt_o) > 4 else _why_tgt_o
                    )
                    _why_pat_o = re.escape(_why_stem_o) + r"\w*"
                    _max_why = max((a for _, a in ordered), default=0.0)
                    for _wi, (_wr, _wa) in enumerate(ordered):
                        _, _, _wb = parse_topic_lineage(_wr.fragment)
                        _wb_l = _wb.lower()
                        _wpos = _wb_l.find(_why_stem_o[:5])
                        if (
                            _wpos != -1
                            and _wpos <= 20
                            and re.search(rf"\b{_why_pat_o}\b", _wb_l[:120])
                        ):
                            ordered[_wi] = (_wr, _max_why + 100.0)
                            break
            elif _is_condition_query(query):
                # CONDITION override: the residual that directly describes the
                # absence/failure of the queried entity wins over any residual
                # that merely has a high Bellman score from prior oscillations.
                _cond_abs = re.search(
                    r"(?:if there (?:is|are) no|without|if not)\s+(\w+)",
                    query.lower(),
                )
                if _cond_abs and len(_cond_abs.group(1)) >= 5:
                    _cond_noun = _cond_abs.group(1)
                    _max_cond = max((a for _, a in ordered), default=0.0)
                    for _ci, (_cr, _ca) in enumerate(ordered):
                        _, _, _cb = parse_topic_lineage(_cr.fragment)
                        _cb_l = _cb.lower()
                        if re.search(
                            rf"without {_cond_noun}|no {_cond_noun}\b|{_cond_noun} cannot\b",
                            _cb_l,
                        ) and _frame(_cr) == "CONDITION":
                            ordered[_ci] = (_cr, _max_cond + 100.0)
                            break

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

            def _body_text(text: str) -> str:
                text = text.strip()
                parts = text.split("::", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
                if " | " in text:
                    return text.split(" | ", 1)[1].strip()
                if len(parts) == 2:
                    return parts[1].strip()
                return text

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
                full_penalty = 0.0 if _is_full_fragment(res.fragment) else 1.0
                # Carrier boost is already baked into `score` (adjusted) from the
                # _vibrate_residuals carrier pass; no separate vibrated_rank needed.
                return (score, force, exact, tag_hit, full_penalty, preconcept, soft)

            ordered.sort(key=rank_key, reverse=True)
            primary_res: Optional[Residual] = None
            primary_text = ""
            support_residuals: List[Residual] = []
            support_texts: List[str] = []

            for res, score in ordered:
                if not self._passes_synthesize_primary_admission(
                    res,
                    score,
                    qset,
                    q_lower,
                ):
                    continue
                primary_res = res
                primary_text = res.fragment.strip()
                break
            if not primary_text:
                self.invention_refusals += 1
                return self._REFUSAL

            # Off-target gate: if the primary has zero evidence match against the
            # query AND the query carries ≥3 distinctive terms, it was selected
            # purely by Bellman weight on a shared entity token. Prefer empty over
            # a confidently wrong answer (e.g. "What color is HyperSeed binary?").
            if primary_res is not None:
                _, _, _ot_body = parse_topic_lineage(primary_res.fragment)
                _ot_ev = _evidence_score(query, _ot_body)
                if _ot_ev == 0.0:
                    _ot_q_words = [w.strip("?.,!") for w in query.lower().split()
                                   if len(w) > 3 and w.strip("?.,!") not in _EVIDENCE_STOP]
                    if len(_ot_q_words) >= 3:
                        self.invention_refusals += 1
                        return self._REFUSAL

            primary_full = _is_full_fragment(primary_text)
            primary_body = _body_text(primary_text).lower()

            # Wave rule: secondary must be net-positive AND not the opposite
            # role for this intent (out-of-phase residuals cancel instead of
            # appearing as related context).
            preferred_role: Optional[str] = (
                "CONDITION"  if (_is_condition_query(query) or intent == "when") else
                "DEFINITION" if _is_definition_query(query) else
                "MECHANISM"  if (lin_intent == "HOW" or _is_action_query(query)) else
                "WHY"        if intent in ("why", "diagnose") else
                None
            )
            _opposite_role = {"MECHANISM": "CONDITION", "CONDITION": "MECHANISM",
                               "DEFINITION": "MECHANISM", "WHY": "DEFINITION"}

            for res, score in ordered:
                if primary_res is not None and res.residual_id == primary_res.residual_id:
                    continue
                if score < 0.44:
                    continue
                # Wave: secondary must be net-positive (constructive wins).
                if score <= 0:
                    continue
                cand = res.fragment.strip()
                cand_body = _body_text(cand).lower()
                if not cand_body or cand_body == primary_body:
                    continue
                if primary_res is None or not _intent_support_compatible(
                    intent_cell,
                    primary_res,
                    res,
                ):
                    continue
                if not self._passes_synthesize_primary_admission(
                    res,
                    score,
                    qset,
                    q_lower,
                ):
                    continue
                cand_full = _is_full_fragment(cand)
                if primary_full and cand_full:
                    continue
                if cand_full and not primary_full:
                    continue
                # Wave: reject secondary whose role is out-of-phase with intent.
                if preferred_role is not None:
                    opp = _opposite_role.get(preferred_role)
                    if opp and _frame(res) == opp:
                        continue
                # Phase-family check: if the candidate was in the carrier top-6,
                # only accept it as secondary if it settled in the same phase family
                # as the query carrier (+Q_ref). Anti-phase candidates cancel rather
                # than appear as related context.
                if (
                    in_phase_set
                    and res.residual_id in carrier_boosts
                    and res.residual_id not in in_phase_set
                ):
                    continue
                soft = fuzzy_token_hits(qset, res.content_set) if qset else 0.0
                if qset and soft < 0.16 and q_lower not in cand.lower():
                    continue
                support_residuals.append(res)
                support_texts.append(cand)
                if len(support_residuals) >= 2:
                    break

            winners = [primary_res] if primary_res is not None else []
            winners.extend(support_residuals)
            self._bellman_update(
                winners,
                reward=0.88 if (intent == "diagnose" or freq.get("class") == "quantity") else 0.78,
            )
            answer = format_intent_cell_answer(
                intent_cell,
                primary_text,
                support_texts,
            )
            if not answer:
                self.invention_refusals += 1
                return self._REFUSAL
            self.or_events += 1  # objective-reduction event
            return answer
        return "Unknown mode"

    def verify_integrity(self) -> Tuple[bool, str]:
        """Verify hash chain integrity."""
        ok, message = self.field.verify_chain()
        if ok and self.lock_count:
            return (
                True,
                f"chain intact ({self.lock_count} residuals; "
                f"{len(self.field.residuals)} paired records)",
            )
        return ok, message

    def status(self) -> Dict[str, Any]:
        # field.status() acquires field._lock and returns chain health and
        # governance summary atomically (consistent with concurrent store()).
        field_st = self.field.status()
        return {
            "void": self.name,
            "locked": field_st["residual_count"],
            "lock_count": self.lock_count,
            "project_count": self.project_count,
            "refusals": self.invention_refusals,
            "chain_ok": field_st["chain_ok"],
            "chain_msg": field_st["chain_msg"],
            "chain_tip": field_st["chain_tip"],
            "layers": field_st["layers"],
            "seeds": field_st["seeds"],
            "nodes": list(self.connected.keys()),
            "uptime_sec": round(time.time() - self.start_time, 1),
            "pure_harness": self.pure_harness.status(),
            "memory": field_st["memory"],
        }
