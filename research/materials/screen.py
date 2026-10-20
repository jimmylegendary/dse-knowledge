import re

HUMAN_ATTITUDE = re.compile(r'\b(perceptions?|attitudes?|ethnograph\w*|questionnaires?|interviews?)\b|\buser stud(?:y|ies)\b|\b(?:users?|developers?|students?|humans?|public|consumers?).{0,55}\b(?:trust|acceptance|adoption)\b|\btrust.{0,18}(?:ai|llm|large language|code)\b|\b(?:social|societal).{0,20}(?:impact|implication)\b',re.I)
DIRECT_TECHNICAL = re.compile(r'\b(cpu|gpu|fpga|asic|hbm|dram|sram|bandwidth|cache|compiler|kernel|microarchitecture|benchmark|flops|throughput|latency|quantiz\w*|prun\w*|vlsi|rtl)\b|\b(?:unit tests?|test cases?|code correctness|execution time|memory bandwidth|model architecture|neural architecture|attention mechanism|learning algorithm|model size|model parameter|token count|token budget|inference cost|inference latency|batch size)\b|pass@\d',re.I)

def social_reference_without_dse_evidence(title, head):
    text=(title or '')+' . '+(head or '')
    return bool(HUMAN_ATTITUDE.search(text) and not DIRECT_TECHNICAL.search(text))

def disambiguate_category(category,title):
    # Numerical geometry is supporting simulation mathematics, not the
    # polyhedral loop-transform compiler domain sharing the same word.
    if category=='compiler_kernel' and re.search(r'finite.element|finite.volume|nonconforming|discretiz|discretis|\bPDE\b',title,re.I) and not re.search(r'compiler|cuda|gpu|llvm|mlir|kernel|code.generation|loop.til',title,re.I):
        return 'simulation_measurement'
    return category

class Screen:
    """Deterministic contextual keyword screen over title + observed abstract."""

    def __init__(self, pol):
        self.pol = pol
        self.sm = pol["screening_model"]
        self.domains = []
        for name, spec in pol["domains"].items():
            terms = []
            for t in spec["terms"]:
                terms.append((t["t"], float(t["w"]), re.compile(t["rx"], re.I)))
            self.domains.append((name, spec["priority"], terms))
        self.domains.sort(key=lambda x: x[1])
        self.term_anchors = {}
        for name, _, terms in self.domains:
            for index, (label, weight, pattern) in enumerate(terms):
                words = re.findall(r'[a-z0-9]+',label.lower())
                if not words:continue
                anchor = max(words,key=len)[:3]
                self.term_anchors.setdefault(anchor,[]).append((name,index,label,weight,pattern))
        self.bio = [(b, re.compile(r"(?<![a-z0-9])" + re.escape(b) + r"[a-z]*(?![a-z0-9])", re.I))
                    for b in pol["bio_markers"]]
        self.ctx_required = bool(self.sm.get("computing_context_required"))
        self.ctx = [(c, re.compile(r"(?<![a-z0-9])" + re.escape(c) + r"[a-z]*(?![a-z0-9])", re.I))
                    for c in self.sm.get("computing_context_terms", [])]
        self.tw = float(self.sm["title_weight"])
        self.aw = float(self.sm["abstract_weight"])
        self.min_abs = int(self.sm["min_abstract_chars"])
        self.min_title = int(self.sm["min_title_chars"])
        self.thresh = float(self.sm["eligible_min_domain_score"])
        self.core_w = float(self.sm["core_weight"])
        hardware = r'\b(cpu|gpu|fpga|asic|processor|microprocessor|hardware|chiplet|chip|semiconductor|silicon|circuit|transistor|risc-v|x86|isa|dram|sram|hbm|cmos|vlsi|system.on.chip|soc|cache|register|accelerator|computer|computing)\b'
        computing = hardware + r'|\b(software|compiler|cuda|ptx|llvm|mlir|runtime|server|datacenter|data.center|distributed.system|parallel|simulator|gem5|tensor|neural.network|machine.learning|deep.learning|transformer|language.model|llm|benchmark|computer.experiment)\b'
        self.domain_context = {
            'hardware_architecture': re.compile(hardware + r'|neural architecture search', re.I),
            'memory_interconnect': re.compile(hardware + r'|\b(software|operating.system|distributed|parallel|network.on.chip|network.interconnect|rdma|all.reduce)\b', re.I),
            'power_thermal_packaging': re.compile(hardware + r'|\b(data.center|datacenter|server|computer|computing|cooling.system)\b', re.I),
            'compiler_kernel': re.compile(computing + r'|\b(loop.nest|polyhedral|code.generation|source.code|vectorization|vectorisation|gemm|matrix.multiplication)\b', re.I),
            'llm_model_workload': re.compile(r'\b(language.model|llm|neural.network|deep.learning|self.attention|attention.mechanism|attention.layer|multi.head.attention|transformer.model|transformer.architecture|transformer.network|tool.call|function.call)\w*\b', re.I),
            'serving_scheduling': re.compile(hardware + r'|\b(software|runtime|server|datacenter|data.center|hpc|cloud.computing|compute.cluster|multi.tenant|edge.computing|cloud.resource|operating.system|inference|workload|neural.network|cluster.scheduling|computer|computing)\b', re.I),
            'simulation_measurement': re.compile(computing + r'|\b(network.performance|distributed|high.performance.computing)\b', re.I),
            'dse_optimization': re.compile(computing + r'|\b(bayesian.optim|multi.objective|multiobjective|pareto|design.space|surrogate.model|active.learning|reinforcement.learning)\w*\b', re.I),
            'provenance_experiment': re.compile(computing + r'|\b(data.provenance|workflow|experiment.tracking|reproducib)\w*\b', re.I),
        }

    def score(self, title, abstract):
        tl = title.lower()
        al = abstract.lower()
        best = None
        all_hits = {}
        candidate_terms = {}
        anchors = {word[:3] for word in re.findall(r'[a-z0-9]+',tl+' '+al)}
        for anchor in anchors:
            for name,index,label,weight,pattern in self.term_anchors.get(anchor,[]):
                candidate_terms.setdefault(name,{})[index]=(label,weight,pattern)
        for name, prio, terms in self.domains:
            score = 0.0
            hits = []
            for index,(label,w,rx) in sorted(candidate_terms.get(name,{}).items()):
                wscore = 0.0
                if label.lower() in tl and rx.search(title):
                    wscore += w * self.tw
                if label.lower() in al and rx.search(abstract):
                    wscore += w * self.aw
                if wscore > 0:
                    score += wscore
                    hits.append((label, w, wscore))
            if hits:
                all_hits[name] = hits
            context = self.domain_context.get(name)
            if not hits or (context and not context.search(title + ' . ' + abstract)):
                continue
            if best is None or score > best[1]:
                best = (name, score, hits)
        if best is None:
            return None
        return best

    def ctx_hits(self, text):
        low = text.lower()
        return [c for c, rx in self.ctx if c.lower() in low and rx.search(text)]

    def bio_hits(self, text):
        out = []
        low = text.lower()
        for b, rx in self.bio:
            if b in low and rx.search(text):
                out.append(b)
        return out

    def decide(self, title, abstract, fields_of_study):
        t = (title or "").strip()
        a = (abstract or "").strip()
        if len(a) < self.min_abs:
            return {"decision": "pending", "category": None,
                    "reason": "no_public_abstract_in_api_response" if not a else
                              "abstract_shorter_than_min_chars",
                    "access_status": "metadata_only_no_head",
                    "matched_terms": [], "score": 0.0}
        if len(t) < self.min_title:
            return {"decision": "pending", "category": None, "reason": "title_too_short",
                    "access_status": "metadata_only_no_head", "matched_terms": [], "score": 0.0}
        if social_reference_without_dse_evidence(t,a):
            return {"decision":"rejected","category":None,"reason":"nontechnical_human_attitude_study","access_status":"public_head_observed","matched_terms":[],"score":0.0}
        best = self.score(t, a)
        if best is None:
            return {"decision": "rejected", "category": None, "reason": "no_topic_terms",
                    "access_status": "public_head_observed", "matched_terms": [], "score": 0.0}
        dname, dscore, hits = best
        core = [h for h in hits if h[1] >= self.core_w]
        if not core or dscore < self.thresh:
            return {"decision": "rejected", "category": dname,
                    "reason": "insufficient_topic_evidence(core=%d,score=%.1f)" % (len(core), dscore),
                    "access_status": "public_head_observed",
                    "matched_terms": [h[0] for h in hits][:12], "score": dscore}
        # Hardware used for medical workloads remains hardware knowledge. A
        # bone/tissue microarchitecture paper cannot pass the hardware gate
        # merely because it uses the same word or mentions energy/modeling.
        if self.ctx_required:
            ctx = self.ctx_hits(t + " . " + a)
            if not ctx:
                return {"decision": "rejected", "category": dname,
                        "reason": "no_computing_context(score=%.1f)" % dscore,
                        "access_status": "public_head_observed",
                        "matched_terms": [h[0] for h in hits][:12], "score": dscore}
        fos = [x.lower() for x in (fields_of_study or [])]
        if fos and "computer science" not in fos and dscore <= float(self.sm["off_field_max_score_without_cs"]):
            return {"decision": "rejected", "category": dname,
                    "reason": "off_field(fields=%s,score=%.1f)" % ("|".join(fos[:4]), dscore),
                    "access_status": "public_head_observed",
                    "matched_terms": [h[0] for h in hits][:12], "score": dscore}
        return {"decision": "eligible", "category": disambiguate_category(dname,t),
                "reason": "technical_context_v2(core=%d,score=%.1f)" % (len(core), dscore),
                "access_status": "public_head_observed",
                "matched_terms": [h[0] for h in sorted(hits, key=lambda x: -x[2])][:12],
                "score": dscore}
