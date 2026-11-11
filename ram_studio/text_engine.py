"""Algorithmic RAM-seeded text synthesizer (Markov chains, Haiku, Poetry, Prose, Kernel Logs)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import math
import re
from typing import Dict, List, Optional, Tuple

from ram_studio.ram_source import RAMEntropyPool, shannon_entropy

TEXT_STYLES: Dict[str, str] = {
    "markov": "Chaîne de Markov RAM",
    "haiku": "Haïku (5-7-5)",
    "poem": "Poème Structuré",
    "prose": "Prose / Chronique Mémoire",
    "code_log": "Pseudo-Code & Logs Poétiques",
}

LANGUAGES: Dict[str, str] = {
    "fr": "Français",
    "en": "English",
}

LENGTH_PRESETS: Dict[str, int] = {
    "short": 4,
    "medium": 8,
    "long": 14,
}

# Built-in rich thematic corpora for Markov chains & Prose
_CORPUS_FR = """
Dans le silence électrique de la mémoire vive, chaque octet trace une constellation éphémère.
Les processus dorment puis s'éveillent comme des navires traversant un océan de silicium bleu.
Sous la surface des registres, une symphonie invisible tisse des accords d'ombre et de lumière.
L'horloge du processeur bat la mesure d'un rêve mathématique où les adresses deviennent poèmes.
Parfois une page mémoire s'illumine, révélant l'écho lointain d'une fenêtre oubliée.
Les octets voyagent en silence entre les circuits dorés, guidés par le souffle du hasard.
La nuit numérique porte des rivières d'ambre et des jardins de cristal fractals.
Chaque bit inverse le reflet d'un astre ancien gravé dans la trame du temps.
Les algorithmes écoutent le murmure des données vivantes et traduisent l'invisible en harmonie.
Une onde lente traverse le cœur de la machine, transformant le bruit brut en mélodie claire.
Les fenêtres s'ouvrent sur des horizons de verre, peuplés d'ombres géométriques et d'étincelles.
Au sommet de la pile, une pensée fugitive attend son tour pour devenir image, son ou verset.
Les vagues magnétiques caressent la mémoire profonde comme le vent soulève la brume du matin.
Rien ne se perd tout à fait tant qu'une étincelle parcourt encore les chemins de cuivre.
Le hasard pur n'existe pas ici, seulement des courants secrets qui cherchent leur forme exacte.
"""

_CORPUS_EN = """
Inside the quiet glow of live memory, every byte sketches an ephemeral constellation.
Processes drift like luminous vessels crossing an ocean of cobalt silicon and glass.
Beneath the address space, an invisible symphony weaves chords of shadow and crystalline light.
The system clock keeps time for a mathematical dream where raw offsets turn into poetry.
Sometimes a memory page ignites, echoing the distant pulse of an awakened window.
Bytes travel silently across copper pathways, guided by the tide of living entropy.
The digital night carries rivers of amber and gardens of self-similar fractal geometry.
Each bit reverses the reflection of an ancient star etched into the fabric of time.
Algorithms listen closely to the murmur of active threads and translate noise into harmony.
A slow wave glides across the silicon core, shaping volatile fragments into clear melody.
Windows open onto glass horizons filled with geometric echoes and drifting sparks.
At the crest of the stack, a fleeting thought waits to become image, sound, or verse.
Magnetic tides brush against deep caches just as morning wind lifts silver mist.
Nothing truly vanishes while a quiet current still travels along the golden bus.
"""

# Syllable-tagged phrases/fragments for authentic 5-7-5 Haiku construction
_HAIKU_FR_5 = [
    "L'ombre du cristal",
    "Un octet s'éveille",
    "Lueur de silicium",
    "Souffle de mémoire",
    "Vague électrique",
    "Écho dans la nuit",
    "Flux d'or et d'azur",
    "Silence du cœur",
    "Goutte de lumière",
    "Fil d'argent subtil",
    "Aube numérique",
    "Songe d'infini",
]

_HAIKU_FR_7 = [
    "Les données glissent sans bruit",
    "Un phare éclaire l'oubli",
    "Le temps pulse dans les fils",
    "Une étoile naît du flux",
    "Le miroir retient l'instant",
    "Des cristaux chantent tout bas",
    "L'horizon change de forme",
    "La machine rêve en paix",
    "Chaque adresse ouvre un ciel",
    "Le hasard devient musique",
]

_HAIKU_EN_5 = [
    "Silver memory",
    "Quiet silicon",
    "Bytes drift in the dark",
    "Electric horizon",
    "Faint harmonic pulse",
    "Echoes in the core",
    "Glass and copper tide",
    "Starlight on the bus",
    "Shadow turns to song",
    "A fleeting signal",
]

_HAIKU_EN_7 = [
    "Patterns bloom inside the stream",
    "Silent pages catch the dawn",
    "Waves of logic softly breathe",
    "Light unfolds along the grid",
    "Hidden music fills the void",
    "Drifting threads align in peace",
    "Random sparks begin to sing",
    "Mirrors hold a changing sky",
]

# Rhyming / assonant poetic line pairs (group_id -> lines) for structured poems
_POEM_PAIRS_FR: List[Tuple[str, str]] = [
    ("Sous les circuits d'argent où la mémoire veille,", "Un fragile rayon soudain s'ouvre et s'éveille."),
    ("Chaque octet endormi garde un secret d'azur,", "Et trace dans le noir un horizon plus pur."),
    ("L'onde lente grandit au cœur de la machine,", "Comme un vent d'équinoxe au creux de la colline."),
    ("Les pages de cristal reflètent l'infini,", "Dans un chant mesuré que le temps a béni."),
    ("Sur le fil invisible où dansent les signaux,", "La lumière répond au murmure des eaux."),
    ("Une note s'élève et traverse l'espace,", "Effaçant doucement la poussière et la trace."),
    ("Des mondes géométriques éclosent sans effort,", "Tissés de lueur froide et de poussière d'or."),
    ("Le hasard apprivoisé devient architecture,", "Et grave son dessin sur la trame future."),
]

_POEM_PAIRS_EN: List[Tuple[str, str]] = [
    ("Across the quiet lanes where living caches gleam,", "A silver thread awakes inside a crystal dream."),
    ("Each drifting byte preserves a spark of distant sky,", "And paints a glowing arc as silent cycles fly."),
    ("A gentle current moves beneath the copper floor,", "Unlocking hidden songs behind a darkened door."),
    ("Within the shifting grid of shadow and design,", "The scattered fragments meet and form a steady line."),
    ("No pulse is ever lost along the winding trace,", "It echoes through the void and settles into grace."),
    ("Geometric blossoms turn upon a velvet sea,", "While fleeting numbers hum a quiet harmony."),
]


@dataclass
class TextConfig:
    """Configuration for algorithmic RAM-seeded text synthesis."""

    style: str = "markov"  # markov, haiku, poem, prose, code_log
    language: str = "fr"
    length: str = "medium"  # short, medium, long
    line_count: int = 8
    temperature: float = 0.85  # 0.1 .. 2.0
    markov_order: int = 2  # 1 or 2
    repetition_penalty: float = 0.45  # 0.0 .. 1.0
    seed_text: str = ""
    custom_corpus: str = ""
    seed_override: str = ""
    read_step: int = 256


@dataclass
class TextResult:
    """Generated text output with RAM entropy diagnostics."""

    text: str
    ram_shannon_entropy: float
    seed_hex: str
    tokens_generated: int


class _RAMDeterministicChoice:
    """Deterministic byte-backed PRNG seeded from captured RAM snapshot."""

    def __init__(self, ram_bytes: bytes):
        self.key = hashlib.blake2b(ram_bytes, digest_size=64).digest()
        self.counter = 0
        self.buf = bytearray()

    def _next_float(self) -> float:
        if len(self.buf) < 4:
            self.buf.extend(
                hashlib.blake2b(self.key + self.counter.to_bytes(8, "little"), digest_size=64).digest()
            )
            self.counter += 1
        val = int.from_bytes(self.buf[:4], "little")
        del self.buf[:4]
        return val / 4294967296.0

    def choice(self, seq):
        return seq[int(self._next_float() * len(seq)) % len(seq)]

    def rand_bytes(self, n: int) -> bytes:
        out = bytearray()
        while len(out) < n:
            out.append(int(self._next_float() * 256) % 256)
        return bytes(out)

    def weighted_choice(self, items_weights: List[Tuple[str, float]], temperature: float) -> str:
        if len(items_weights) == 1:
            return items_weights[0][0]
        temp = max(0.08, float(temperature))
        # Temperature-scaled weights: w^(1/T)
        inv_t = 1.0 / temp
        scaled = [(item, (max(1e-6, w)) ** inv_t) for item, w in items_weights]
        total = sum(w for _, w in scaled)
        target = self._next_float() * total
        acc = 0.0
        for item, w in scaled:
            acc += w
            if acc >= target:
                return item
        return scaled[-1][0]


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9'’-]+|[.,;:!?]", text)


def _detokenize(tokens: List[str]) -> str:
    out: List[str] = []
    for tok in tokens:
        if tok in (".", ",", ";", ":", "!", "?") and out:
            out[-1] = out[-1] + tok
        else:
            out.append(tok)
    s = " ".join(out)
    # Capitalize sentence starts
    sentences = re.split(r"([.!?]\s+)", s)
    rebuilt = []
    for part in sentences:
        if part and part[0].isalpha():
            rebuilt.append(part[0].upper() + part[1:])
        else:
            rebuilt.append(part)
    return "".join(rebuilt)


def _generate_markov(config: TextConfig, rng: _RAMDeterministicChoice, sentence_target: int) -> Tuple[str, int]:
    base_corpus = _CORPUS_FR if config.language == "fr" else _CORPUS_EN
    corpus = (config.custom_corpus.strip() + "\n" + base_corpus) if config.custom_corpus.strip() else base_corpus
    tokens = _tokenize(corpus)
    order = 2 if config.markov_order >= 2 and len(tokens) > 12 else 1

    transitions: Dict[Tuple[str, ...], Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    starts: List[Tuple[str, ...]] = []
    for i in range(len(tokens) - order):
        key = tuple(tokens[i : i + order])
        nxt = tokens[i + order]
        transitions[key][nxt] += 1
        if i == 0 or tokens[i - 1] in (".", "!", "?"):
            starts.append(key)

    if not starts:
        starts = list(transitions.keys())

    # Optional seed prompt matching
    seed_tokens = _tokenize(config.seed_text.strip())
    state = None
    generated: List[str] = []
    if seed_tokens:
        generated.extend(seed_tokens)
        if len(seed_tokens) >= order:
            cand = tuple(seed_tokens[-order:])
            if cand in transitions:
                state = cand
        if state is None:
            last_tok = seed_tokens[-1].lower()
            matching = [k for k in transitions if k[-1].lower() == last_tok]
            if matching:
                state = rng.choice(matching)

    if state is None:
        state = rng.choice(starts)
        generated.extend(state)

    recent_window: List[str] = list(generated[-10:])
    sentences_done = 0
    max_tokens = max(24, sentence_target * 16)
    penalty = max(0.0, min(0.95, float(config.repetition_penalty)))

    while len(generated) < max_tokens and sentences_done < sentence_target:
        choices = transitions.get(state)
        if not choices:
            state = rng.choice(starts)
            if generated and generated[-1] not in (".", "!", "?"):
                generated.append(".")
                sentences_done += 1
            generated.extend(state)
            continue

        weighted: List[Tuple[str, float]] = []
        for tok, cnt in choices.items():
            w = float(cnt)
            if tok.lower() in [r.lower() for r in recent_window]:
                w *= max(0.08, 1.0 - penalty)
            weighted.append((tok, w))

        pick = rng.weighted_choice(weighted, config.temperature)
        generated.append(pick)
        recent_window.append(pick)
        if len(recent_window) > 10:
            recent_window.pop(0)
        if pick in (".", "!", "?"):
            sentences_done += 1
        state = tuple(generated[-order:])

    if generated and generated[-1] not in (".", "!", "?"):
        generated.append(".")
    return _detokenize(generated), len(generated)


def _generate_haiku(config: TextConfig, rng: _RAMDeterministicChoice, stanzas: int) -> Tuple[str, int]:
    l5 = _HAIKU_FR_5 if config.language == "fr" else _HAIKU_EN_5
    l7 = _HAIKU_FR_7 if config.language == "fr" else _HAIKU_EN_7
    blocks: List[str] = []
    toks = 0
    n_haikus = max(1, (stanzas + 1) // 3)
    for _ in range(n_haikus):
        a = rng.choice(l5)
        b = rng.choice(l7)
        c = rng.choice([x for x in l5 if x != a] or l5)
        blocks.append(f"{a}\n{b}\n{c}")
        toks += len(a.split()) + len(b.split()) + len(c.split())
    return "\n\n".join(blocks), toks


def _generate_poem(config: TextConfig, rng: _RAMDeterministicChoice, lines_target: int) -> Tuple[str, int]:
    pairs = _POEM_PAIRS_FR if config.language == "fr" else _POEM_PAIRS_EN
    n_stanzas = max(1, (lines_target + 3) // 4)
    stanzas: List[str] = []
    toks = 0
    for _ in range(n_stanzas):
        p1 = rng.choice(pairs)
        p2 = rng.choice([p for p in pairs if p != p1] or pairs)
        # Alternate ABAB structure cleanly
        quatrain = [p1[0], p2[0], p1[1], p2[1]]
        stanzas.append("\n".join(quatrain))
        toks += sum(len(line.split()) for line in quatrain)
    return "\n\n".join(stanzas), toks


def _generate_prose(
    config: TextConfig,
    rng: _RAMDeterministicChoice,
    ram_bytes: bytes,
    lines_target: int,
) -> Tuple[str, int]:
    ent = shannon_entropy(ram_bytes)
    avg_byte = sum(ram_bytes) / max(1, len(ram_bytes))
    if config.language == "fr":
        intro = (
            f"[Observation Mémoire • Entropie {ent:.2f} b/o • Densité moyenne {avg_byte:.1f}/255]"
        )
    else:
        intro = (
            f"[Memory Chronicle • Entropy {ent:.2f} b/B • Mean density {avg_byte:.1f}/255]"
        )
    body, toks = _generate_markov(config, rng, max(3, lines_target))
    paragraphs = [intro]
    sentences = re.split(r"(?<=[.!?])\s+", body)
    chunk_sz = max(2, len(sentences) // max(1, min(3, lines_target // 3)))
    for i in range(0, len(sentences), chunk_sz):
        paragraphs.append(" ".join(sentences[i : i + chunk_sz]))
    return "\n\n".join(paragraphs), toks + len(intro.split())


def _generate_code_log(
    config: TextConfig,
    rng: _RAMDeterministicChoice,
    ram_bytes: bytes,
    lines_target: int,
) -> Tuple[str, int]:
    verbs = (
        ["échantillonner", "harmoniser", "projeter", "filtrer", "trier", "transposer", "illuminer"]
        if config.language == "fr"
        else ["sample", "harmonize", "project", "filter", "weave", "transpose", "illuminate"]
    )
    nouns = (
        ["page_mémoire", "vecteur_onde", "registre_flux", "cristal_ram", "trame_azur", "horloge_cœur"]
        if config.language == "fr"
        else ["memory_page", "wave_vector", "stream_register", "ram_lattice", "azure_frame", "core_clock"]
    )
    notes = (
        ["// la mémoire respire en silence", "// résonance stable", "// dérive fractale détectée", "// harmonique alignée"]
        if config.language == "fr"
        else ["// memory breathes quietly", "// resonance stable", "// fractal drift detected", "// harmonic locked"]
    )
    lines: List[str] = []
    for i in range(max(3, lines_target)):
        addr = int.from_bytes(rng.rand_bytes(4), "big") & 0xFFFFFFFF
        b = ram_bytes[i % len(ram_bytes)]
        v = rng.choice(verbs)
        n = rng.choice(nouns)
        c = rng.choice(notes)
        lines.append(f"0x{addr:08X} | {v}({n}, val={b:3d}, phi={b / 255.0:.3f})  {c}")
    return "\n".join(lines), len(lines) * 6


def generate_text_from_bytes(ram_bytes: bytes, config: TextConfig) -> TextResult:
    """Synthesize algorithmic text seeded from `ram_bytes` (or seed_override)."""
    if config.seed_override.strip():
        effective_bytes = hashlib.blake2b(config.seed_override.strip().encode("utf-8"), digest_size=64).digest()
    elif not ram_bytes:
        effective_bytes = b"\x42\x99\x13\x7f" * 32
    else:
        effective_bytes = ram_bytes

    ent = shannon_entropy(effective_bytes)
    rng = _RAMDeterministicChoice(effective_bytes)
    lines_target = max(2, int(config.line_count or LENGTH_PRESETS.get(config.length, 8)))

    style = config.style.lower()
    if style == "haiku":
        text, toks = _generate_haiku(config, rng, lines_target)
    elif style == "poem":
        text, toks = _generate_poem(config, rng, lines_target)
    elif style == "prose":
        text, toks = _generate_prose(config, rng, effective_bytes, lines_target)
    elif style == "code_log":
        text, toks = _generate_code_log(config, rng, effective_bytes, lines_target)
    else:
        text, toks = _generate_markov(config, rng, lines_target)

    seed_hex = hashlib.sha256(effective_bytes).hexdigest()[:16].upper()
    return TextResult(
        text=text,
        ram_shannon_entropy=round(ent, 3),
        seed_hex=seed_hex,
        tokens_generated=toks,
    )


def generate_text(ram_pool: RAMEntropyPool, config: TextConfig) -> TextResult:
    """Sample live RAM bytes and synthesize algorithmic text."""
    ram_bytes = ram_pool.sample_bytes(512, step=config.read_step)
    return generate_text_from_bytes(ram_bytes, config)
