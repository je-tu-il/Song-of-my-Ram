"""RAM-seeded password, passphrase, and key generator with entropy pool analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
import base64
import hashlib
import math
import os
import string
from typing import Dict, List, Optional

from ram_studio.ram_source import RAMEntropyPool, shannon_entropy

AMBIGUOUS_CHARS = set("0Ool1I|`'\"")

# Curated bilingual (FR/Tech/Nature) 256-word dictionary (8 bits/word cleanly)
PASSPHRASE_WORDS: List[str] = (
    "acier aigle alchimie alpage ambre ancre apogee ardoise argile aster astre atlas aube aurore "
    "azur balise bambou basalte bastion belier berceau beryl biseau blason bocage boreale bouleau "
    "braise brume bulle cabestan cactus cadence calice calme canopee canyon caprice carbone cascade "
    "caverne cedre celeste cerise chalet chaleur champ chene chiffre chypre ciel cimier citadelle "
    "clarte clematite climat clocher cobalt codeur comete compas corail corbeau cosmos couchant "
    "cratere cristal cuivre cyclone cygne dague dahlia delta diamant diurne dolmen domaine doree "
    "dragon dune ebonite eclat eclipse ecume edifice eflore elan elixir emeraude empire enclume "
    "energie enigme encre eolienne epice epure equinoxe erable ermite escale espace espoir etain "
    "etincelle etoile etrange europe eveil exode falaises fanal fantome phare fennec fervente feuillage "
    "fibre figuier filon fjord flamme fleche fleur fleuve florence fluide flux foret forge fortune "
    "fossile foudre foyer fragment frimas frisson frontiere fusion galaxie galet galion garde "
    "garnet geiser genese granit grappe gravite grenat griffe grotte harmonie harpe havre helice "
    "herbier hermine horizon houle humble hydre iceberg icone idylle igloo image impact indigo "
    "infini instinct ionique iris jasmin jaspe java javelot joyau jungle jurassique karma kayak "
    "kelvin kirsch koan labyrinthe lagon laine lame lampe lanterne lapislazuli lavande legende "
    "lemure lentille liane liberte lichen liege lierre ligne lilas limbe limpide linotte lionne "
    "lueur lumiere lunaire lustre lutin lyre magma magnetique magnolia maille majeur malachite "
    "mandala manoir marais marbre maree matrice meandre medaille melodie memoire menhir mercure "
    "meridien mesa metal meteore methode miroir mistral module moisson monade monde monolite "
    "mousson muraille murmure myosotis myrrhe mythe nacelle nadir nausicaa navire nebuleuse nectar "
    "neige neon nerval nexus nimbus nitrate nocturne noeud nordique noyau nuage nuance oasis "
    "obelisque obsidienne ocean octave odyssee ogive olivier ombre omega onde opale opaline "
    "orbite orchidee orion orme osmose ouragan outarde oxyde pagode palais palme pampa panache "
    "papyrus paradis parchemin parfum parsec pascale passeur pastel pavillon pegase pelage penombre "
    "perle persan petale phalene phenix photon piano pierre pignon piolet pixel planete platine "
    "pleiade plume pluton poeme polaire pollen ponant portail poudre prisme prodigue profil "
    "promesse prunelle pulsar pyramide python quartz quasar quete radian radieux rafale ramure "
    "rapsodie rayon recif reflet refuge regate relais relique remous rempart renard repere "
    "resine ressource retour reveil rhapsodie riviere roche rococo romance rosace rosee roseau "
    "ruban rubis ruche ruisseau rune sables sablier safran saphir sarabande satellite saturne "
    "saule savane scarabee sceptre schema science scorie scorpion secteur seisme selenite semence "
    "sentier sequoia serenite serment silex silice sillage silure sirius sirocco solstice sombre "
    "sonate songe sonore source spectre sphere spirale steppe strate stratus stylo suie sulfure "
    "sumac sommet symphonie synchro synthese syrinx tableau talisman tambour tangente tanin "
    "tapisserie telomere tempete temple tempo tenseur terreur textile theorem thuya tiare "
    "tige tigre timbre titan titane toile toison toiture topaze torche torrent totem tourbe "
    "tourbillon trace tramontane transe transit trappe tresor tribu trident trille trilogie "
    "triomphe troika tronc tropique trouble trouveur tuile tulipe toundra turbine turquoise "
    "tuteur typhon ulcere ultime ultraviole univers uranus urne usine utopie vague vaillance "
    "vallee vallon valse vampire vanille vapeur varan vecteur veine velours vendange ventose "
    "verbena verdict verger vermeil vernis versant vertige verveine vestige vibrato victoire "
    "vifargent vigie vigne vigueur village violette virage viscose vision vitesse vitrail "
    "vivace vocalise voilier volcan voltige volume vortex voyage vrille vulcain wagon watte "
    "webinaire xénon xylophone yack yacht yoga yucca zéphyr zénith zéro zeste zibeline zinc "
    "zircon zodiaque zone zoom"
).split()


@dataclass
class PasswordConfig:
    """Configuration for RAM-seeded password generation."""

    mode: str = "password"  # password, passphrase, hex, base64, pin
    length: int = 16
    use_lower: bool = True
    use_upper: bool = True
    use_digits: bool = True
    use_symbols: bool = True
    custom_symbols: str = "!@#$%^&*-_=+?"
    exclude_ambiguous: bool = False
    require_each_class: bool = True
    word_count: int = 5
    separator: str = "-"
    capitalize_words: bool = True
    sample_size: int = 256
    mix_os_urandom: bool = True
    count: int = 1
    target_pid: Optional[int] = None


@dataclass
class PasswordResult:
    """Output bundle including generated secrets and live RAM entropy diagnostics."""

    passwords: List[str]
    entropy_bits: float
    strength_label: str
    ram_shannon_entropy: float
    ram_bytes: bytes
    ram_sample_hex: str
    source_summary: str
    charset_size: int


class _RAMByteStream:
    """Unbiased cryptographic byte expander seeded by live RAM bytes."""

    def __init__(self, ram_bytes: bytes, mix_urandom: bool = True):
        salt = os.urandom(32) if mix_urandom else b"pure_ram_deterministic_salt"
        self.seed_key = hashlib.blake2b(ram_bytes + salt, digest_size=64).digest()
        self.counter = 0
        self.buf = bytearray()

    def _refill(self) -> None:
        block = hashlib.blake2b(
            self.seed_key + self.counter.to_bytes(8, "little"),
            digest_size=64,
        ).digest()
        self.counter += 1
        self.buf.extend(block)

    def rand_below(self, upper: int) -> int:
        """Unbiased integer in [0, upper) via rejection sampling."""
        if upper <= 1:
            return 0
        limit = (0xFFFFFFFF // upper) * upper
        while True:
            while len(self.buf) < 4:
                self._refill()
            val = int.from_bytes(self.buf[:4], "little")
            del self.buf[:4]
            if val < limit:
                return val % upper

    def rand_bytes(self, n: int) -> bytes:
        while len(self.buf) < n:
            self._refill()
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def shuffle(self, items: List[str]) -> None:
        for i in range(len(items) - 1, 0, -1):
            j = self.rand_below(i + 1)
            items[i], items[j] = items[j], items[i]


def _classify_strength(bits: float) -> str:
    if bits < 40:
        return "Faible"
    if bits < 64:
        return "Moyen"
    if bits < 90:
        return "Fort"
    if bits < 128:
        return "Très Fort"
    return "Extrême"


def _filter_chars(chars: str, exclude_ambiguous: bool) -> str:
    if not exclude_ambiguous:
        return chars
    return "".join(c for c in chars if c not in AMBIGUOUS_CHARS)


def generate_passwords_from_bytes(ram_bytes: bytes, config: PasswordConfig, source_summary: str = "") -> PasswordResult:
    """Generate passwords/passphrases/keys directly from provided RAM bytes."""
    if not ram_bytes:
        ram_bytes = os.urandom(max(64, config.sample_size))

    ram_ent = shannon_entropy(ram_bytes)
    stream = _RAMByteStream(ram_bytes, mix_urandom=config.mix_os_urandom)
    count = max(1, min(20, int(config.count)))
    mode = config.mode.lower()
    passwords: List[str] = []
    charset_size = 0
    bits = 0.0

    if mode == "passphrase":
        words_pool = PASSPHRASE_WORDS
        wc = max(3, min(12, int(config.word_count)))
        charset_size = len(words_pool)
        bits = wc * math.log2(charset_size)
        for _ in range(count):
            picked = []
            for _ in range(wc):
                w = words_pool[stream.rand_below(len(words_pool))]
                if config.capitalize_words:
                    w = w.capitalize()
                picked.append(w)
            passwords.append(config.separator.join(picked))
    elif mode == "hex":
        n_chars = max(4, min(256, int(config.length)))
        charset_size = 16
        bits = n_chars * 4.0
        for _ in range(count):
            raw = stream.rand_bytes((n_chars + 1) // 2)
            passwords.append(raw.hex()[:n_chars])
    elif mode == "base64":
        n_chars = max(4, min(256, int(config.length)))
        charset_size = 64
        bits = n_chars * 6.0
        for _ in range(count):
            raw = stream.rand_bytes(max(4, n_chars))
            token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
            passwords.append(token[:n_chars])
    elif mode == "pin":
        n_chars = max(4, min(32, int(config.length)))
        digits = _filter_chars(string.digits, config.exclude_ambiguous) or string.digits
        charset_size = len(digits)
        bits = n_chars * math.log2(charset_size)
        for _ in range(count):
            passwords.append("".join(digits[stream.rand_below(len(digits))] for _ in range(n_chars)))
    else:
        # Standard password mode
        classes: List[str] = []
        if config.use_lower:
            c = _filter_chars(string.ascii_lowercase, config.exclude_ambiguous)
            if c:
                classes.append(c)
        if config.use_upper:
            c = _filter_chars(string.ascii_uppercase, config.exclude_ambiguous)
            if c:
                classes.append(c)
        if config.use_digits:
            c = _filter_chars(string.digits, config.exclude_ambiguous)
            if c:
                classes.append(c)
        if config.use_symbols:
            sym_src = config.custom_symbols or "!@#$%^&*-_=+?"
            c = _filter_chars(sym_src, config.exclude_ambiguous)
            if c:
                classes.append(c)

        if not classes:
            classes = [_filter_chars(string.ascii_letters + string.digits, config.exclude_ambiguous)]

        pool = "".join(dict.fromkeys("".join(classes)))  # Deduplicated ordered charset
        charset_size = len(pool)
        n_chars = max(4, min(128, int(config.length)))
        bits = n_chars * math.log2(max(2, charset_size))

        for _ in range(count):
            chars: List[str] = []
            if config.require_each_class and n_chars >= len(classes):
                for cls in classes:
                    chars.append(cls[stream.rand_below(len(cls))])
            while len(chars) < n_chars:
                chars.append(pool[stream.rand_below(len(pool))])
            stream.shuffle(chars)
            passwords.append("".join(chars))

    return PasswordResult(
        passwords=passwords,
        entropy_bits=round(bits, 1),
        strength_label=_classify_strength(bits),
        ram_shannon_entropy=round(ram_ent, 3),
        ram_bytes=ram_bytes,
        ram_sample_hex=ram_bytes[:32].hex(" ").upper(),
        source_summary=source_summary or f"{len(ram_bytes)} octets RAM",
        charset_size=charset_size,
    )


def generate_passwords(ram_pool: RAMEntropyPool, config: PasswordConfig) -> PasswordResult:
    """Sample live RAM bytes from `ram_pool` and generate passwords + telemetry."""
    sample_sz = max(64, min(4096, int(config.sample_size)))
    ram_bytes = ram_pool.sample_bytes(sample_sz, step=256, pid=config.target_pid, non_zero_bias=True)
    meta = ram_pool.last_telemetry
    names = ", ".join(meta.get("source_names", [])[:3]) or "RAM Locale"
    summary = f"{len(ram_bytes)} octets • Sources: {names} • Entropie RAM: {meta.get('shannon_entropy', 0.0):.2f} b/o"
    return generate_passwords_from_bytes(ram_bytes, config, source_summary=summary)
