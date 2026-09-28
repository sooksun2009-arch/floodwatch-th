"""English wording for the assistant's most common answers.

Kept in its own file, and reached through one helper, so that the Thai path —
which works and which most people use — is not rewritten to add a second
language. A missing key falls back to Thai rather than to an English sentence
somebody half-wrote.

Four question shapes are covered, because they are what people actually ask:
is it flooded at X, is it flooded near me, where is it worst, and where are
the cameras. Anything else still answers in Thai and says so, which is more
use than a machine-translated sentence about water depth.

Numbers keep centimetres and add inches. A visitor who reads "30 cm" has a
number; "12 in" is what decides whether they drive into it.
"""

LEVEL_EN = {
    "normal": "passable as normal",
    "puddle": "standing water, under 10 cm (4 in)",
    "shallow": "flooded 10–30 cm (4–12 in), saloon cars can pass with care",
    "deep": "flooded 30–60 cm (12–24 in)",
    "severe": "flooded over 60 cm (24 in), impassable",
    "closed": "road closed",
}

SITUATION_EN = {
    1: "critically low",
    2: "low",
    3: "normal",
    4: "high, being watched",
    5: "critical, over the bank",
}

SAFETY_NOTE = (
    "\n\nWorth knowing: above about 30 cm (12 in) a saloon car can stall, and "
    "flowing water only 15 cm (6 in) deep can knock a person off their feet. "
    "If the trip can wait, let it."
)

NOT_TRANSLATED = (
    "\n\n[This kind of question is only answered in Thai for now. "
    "Route checks, flooding near a place, the worst areas and cameras all "
    "work in English.]"
)

MESSAGES = {
    # ---------------------------------------------------------- a place
    "place.none": (
        "No confirmed flood reports in {scope} at the moment.\n\n"
        "That means nobody has reported anything — not that the road is "
        "confirmed dry. If you can see flooding, please use the report button "
        "so other people know."
    ),
    "place.cameras": "\n\nThere are {count} traffic cameras near here you can watch live.",
    "place.headline": (
        "{scope} has {count} confirmed flood reports. The worst is {worst}."
    ),
    "place.impassable": (
        "\n\n{count} of these cannot be driven through or are closed to traffic. "
        "Take another way."
    ),
    # ---------------------------------------------------------- near me
    "near.noLocation": (
        "I do not know where you are yet. Tap \"Use my location\" at the corner "
        "of the map, or type a road, district or province — for example "
        "\"is Ramkhamhaeng flooded?\""
    ),
    "near.none": (
        "No confirmed flood reports within 5 km of you.\n\n"
        "If you can see water ahead of you, please report it so others know."
    ),
    "near.cameras": "\n\n{count} traffic cameras near you — watch them live in the list below.",
    "near.some": (
        "Within 5 km of you there are {count} flooded spots. The worst is {worst}.\n\n"
    ),
    # ---------------------------------------------------------- worst
    "worst.none": (
        "There are no confirmed flood reports anywhere in the system right now — "
        "which is good news. If you come across flooding, please send it in."
    ),
    "worst.body": (
        "{count} confirmed flooded spots right now.\n\n"
        "The worst of them:\n{lines}\n\n"
        "Provinces with the most reports: {provinces}"
    ),
    # ---------------------------------------------------------- cameras
    "cams.none": (
        "No traffic cameras registered near {scope}. "
        "({total} in the system altogether.)\n\n"
        "If you know the URL of a camera in that area, the admins can add it."
    ),
    "cams.body": (
        "{count} traffic cameras near {scope} you can watch now:\n{lines}\n\n"
        "Tap a camera name below to open the live picture."
    ),
    # ---------------------------------------------------------- routes
    "route.needEndpoints": (
        "Tell me where from and where to and I will check the route — "
        "for example \"Bang Na to Ramkhamhaeng\" or \"from Silom to Chatuchak\"."
    ),
    "route.unresolved": (
        "I could not find {places} on the map. Try a district, a main road or a "
        "province, or drop a pin on the map instead."
    ),
    # ---------------------------------------------------------- pieces
    "line.report": "• {where} — {label}.{extra}{trust}",
    "line.measured": " Measured {depth} cm ({inches} in).",
    "line.confirmed": " Confirmed by {count}.",
    "line.province": "{name} ({count})",
    "line.camera": "• {name}{dist}{org}{demo}",
    "line.demo": " [sample stream]",
    "scope.country": "the whole country",
    "scope.you": "your location",
    "where.unknown": "location not given",
    "province.unknown": "province not given",
}


def tr(key: str, **kw) -> str | None:
    """English text for key, or None when there is none.

    None is the signal to fall back to Thai. It is deliberately not an empty
    string: a blank answer from a flood assistant is the worst of the three
    possible outcomes.
    """
    template = MESSAGES.get(key)
    return template.format(**kw) if template else None


def level(code: str) -> str:
    return LEVEL_EN.get(code, code)


def depth(cm) -> str:
    """Centimetres with inches beside them, for a reader who thinks in inches."""
    return f"{cm} cm ({round(cm / 2.54)} in)"


# ---------------------------------------------------------------- place names

# Romanised names for the places visitors actually ask about, mapped to the
# Thai the gazetteer holds. Not a transliteration engine: Thai romanisation is
# inconsistent enough that a general one would produce confident wrong matches,
# which on this map means telling someone the wrong district is dry. A short
# list that is right beats a long one that is nearly right.
#
# Keys are lowercase with spaces and hyphens removed, so "Bang Na", "bang-na"
# and "bangna" all arrive the same.
ALIASES = {
    # Bangkok districts and areas
    "bangna": "บางนา", "sukhumvit": "สุขุมวิท", "silom": "สีลม",
    "sathorn": "สาทร", "sathon": "สาทร", "asok": "อโศก", "asoke": "อโศก",
    "siam": "สยาม", "ratchada": "รัชดา", "ratchadaphisek": "รัชดาภิเษก",
    "ladprao": "ลาดพร้าว", "latphrao": "ลาดพร้าว", "ladphrao": "ลาดพร้าว",
    "chatuchak": "จตุจักร", "jatujak": "จตุจักร",
    "ramkhamhaeng": "รามคำแหง", "ramkamhaeng": "รามคำแหง",
    "onnut": "อ่อนนุช", "ekkamai": "เอกมัย", "thonglor": "ทองหล่อ",
    "phrakhanong": "พระโขนง", "prakanong": "พระโขนง",
    "khaosan": "ข้าวสาร", "khaosanroad": "ถนนข้าวสาร",
    "victorymonument": "อนุสาวรีย์ชัยสมรภูมิ",
    "donmuang": "ดอนเมือง", "donmueang": "ดอนเมือง",
    "suvarnabhumi": "สุวรรณภูมิ", "bangkapi": "บางกะปิ",
    "bangkhen": "บางเขน", "minburi": "มีนบุรี", "laksi": "หลักสี่",
    "dindaeng": "ดินแดง", "huaikhwang": "ห้วยขวาง", "huaykwang": "ห้วยขวาง",
    "phayathai": "พญาไท", "bangrak": "บางรัก", "yannawa": "ยานนาวา",
    "thonburi": "ธนบุรี", "bangkhunthian": "บางขุนเทียน",
    "nonthaburi": "นนทบุรี", "pakkret": "ปากเกร็ด",
    "rangsit": "รังสิต", "pathumthani": "ปทุมธานี",
    "samutprakan": "สมุทรปราการ", "bangkok": "กรุงเทพมหานคร",
    # Provinces visitors travel to
    "chiangmai": "เชียงใหม่", "chiangrai": "เชียงราย", "phuket": "ภูเก็ต",
    "pattaya": "พัทยา", "chonburi": "ชลบุรี", "ayutthaya": "พระนครศรีอยุธยา",
    "kanchanaburi": "กาญจนบุรี", "huahin": "หัวหิน",
    "prachuapkhirikhan": "ประจวบคีรีขันธ์", "krabi": "กระบี่",
    "suratthani": "สุราษฎร์ธานี", "kohsamui": "เกาะสมุย", "samui": "เกาะสมุย",
    "udonthani": "อุดรธานี", "khonkaen": "ขอนแก่น", "nakhonratchasima": "นครราชสีมา",
    "korat": "นครราชสีมา", "hatyai": "หาดใหญ่", "songkhla": "สงขลา",
    "phangnga": "พังงา", "sukhothai": "สุโขทัย", "lampang": "ลำปาง",
}


def to_thai_place(text: str) -> str | None:
    """The Thai name for a romanised place in text, if one is listed.

    Looks at the longest runs of Latin letters first, so "is bang na flooded"
    finds "bangna" rather than stopping at "is".
    """
    import re as _re

    words = _re.findall(r"[a-zA-Z]+", text.lower())
    for size in (4, 3, 2, 1):
        for i in range(len(words) - size + 1):
            key = "".join(words[i:i + size])
            if key in ALIASES:
                return ALIASES[key]
    return None
