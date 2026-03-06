import re

def unicode_to_krutidev(text):
    if not text:
        return ""

    # 🚀 0. PRE-PROCESSING: AI OCR Auto-Correction
    # Fixes common AI spelling mistakes before font conversion happens
    # spell_fixes = [
    #     ("किष्त", "किश्त"),
    #     ("किस्त", "किश्त")
    # ]
    # for bad_word, good_word in spell_fixes:
    #     text = text.replace(bad_word, good_word)

    consonants = r'[\u0915-\u0939\u0958-\u095F]'
    halant = r'\u094D'
    chhoti_ee = r'\u093F'
    reph = r'\u0930\u094D'
    matras = r'[\u093E-\u094C\u0962\u0963]'
    anusvara = r'[\u0901\u0902]'

    # 1. REPH (Top R)
    reph_pattern = f'({reph})({consonants}(?:{halant}{consonants})*)({matras}?{anusvara}?)'
    text = re.sub(reph_pattern, r'\2\3\1', text)

    # 2. CHHOTI EE
    cluster_pattern = f'({consonants}(?:{halant}{consonants})*){chhoti_ee}'
    text = re.sub(cluster_pattern, '\u093F\\1', text)

    # 3. STRICTLY ORDERED REPLACEMENTS
    replacements = [
        # Rogue English Quotes
        ("\"", ""), ("'", ""),

        # Brackets
        ("(", "¼"), (")", "½"), ("[", "¼"), ("]", "½"), ("{", "¼"), ("}", "½"),
        ("‘", "^"), ("’", "*"), ("“", "Þ"), ("”", "ß"),
        
        # 🚀 THE FONT FALLBACK HACK FOR PUNCTUATION 🚀
        # Replaces standard '.' and '/' with identical mathematical symbols.
        # This forces Excel to safely fallback to Arial to draw them!
        (".", "\u2024"),   # Replaced with One Dot Leader
        ("॰", "\u2024"),   # Replaced Devanagari abbreviation dot
        ("/", "\u2215"),   # Replaced with Mathematical Division Slash
        
        ("।", "A"), 
        (":", "%"), 
        ("-", "-"),
        
        ("०", "0"), ("१", "1"), ("२", "2"), ("३", "3"), ("४", "4"),
        ("५", "5"), ("६", "6"), ("७", "7"), ("८", "8"), ("९", "9"),

        # Special Conjuncts
        ("क्ष्", "{"), ("त्र्", "«"), ("ज्ञ्", "K~"), ("श्र्", "J~"),
        ("क्ष", "{k"), ("त्र", "«k"), ("ज्ञ", "K"), ("श्र", "J"),
        ("क्र", "Ø"), ("ट्र", "Vª"), ("ड्र", "Mª"),
        ("द्व", "}"), ("द्य", "|"), ("द्ध", ")"), 
        ("ट्ट", "V~V"), ("ड्ड", "M~M"), ("दृ", "n`"), ("कृ", "d`"),

        # R-Modifiers
        ("र्", "Z"),  # Top R (Reph)
        ("्र", "z"),  # Bottom R (Paden Ra)

        # Explicit Half Consonants
        ("क्", "D"), ("ख्", "["), ("ग्", "X"), ("घ्", "?"), ("ङ्", "³~"),
        ("च्", "P"), ("छ्", "N~"), ("ज्", "T"), ("झ्", ">~"), ("ञ्", "¥~"),
        ("ट्", "V~"), ("ठ्", "B~"), ("ड्", "M~"), ("ढ्", "<~"), ("ण्", "."),
        ("त्", "R"), ("थ्", "F"), ("द्", "n~"), ("ध्", "è"), ("न्", "U"),
        ("प्", "I"), ("फ्", "¶"), ("ब्", "C"), ("भ्", "H"), ("म्", "E"),
        ("य्", "¸"), ("ल्", "Y"), ("व्", "O"), ("श्", "\""),
        ("ष्", "'"), ("स्", "L"), ("ह्", "g~"),

        # Full Consonants
        ("क", "d"), ("ख", "[k"), ("ग", "x"), ("घ", "?k"), ("ङ", "³"),
        ("च", "p"), ("छ", "N"), ("ज", "t"), ("झ", ">"), ("ञ", "¥"),
        ("ट", "V"), ("ठ", "B"), ("ड", "M"), ("ढ", "<"), ("ण", ".k"),
        ("त", "r"), ("थ", "Fk"), ("द", "n"), ("ध", "èk"), ("न", "u"),
        ("प", "i"), ("फ", "Q"), ("ब", "c"), ("भ", "Hk"), ("म", "e"),
        ("य", ";"), ("र", "j"), ("ल", "y"), ("व", "o"), ("श", "”k"),
        ("ष", "'k"), ("स", "l"), ("ह", "g"),

        # Vowels
        ("अ", "v"), ("आ", "vk"), ("इ", "b"), ("ई", "bZ"), ("उ", "m"), ("ऊ", "Å"),
        ("ए", ","), ("ऐ", ",S"), ("ओ", "vks"), ("औ", "vkS"), ("ऋ", "Fk"),
        ("ऑ", "vkW"), ("ऍ", "vW"),

        # Matras & Modifiers
        ("ॉ", "kW"), ("ॅ", "W"), ("ा", "k"), ("ि", "f"), ("ी", "h"), 
        ("ु", "q"), ("ू", "w"), ("ृ", "`"), ("े", "s"), ("ै", "S"), 
        ("ो", "ks"), ("ौ", "kS"), ("ं", "a"), ("ँ", "¡"), ("ः", "%"),
        ("़", "+"), ("्", "~") # Catch-all Halant
    ]

    for unicode_char, krutidev_char in replacements:
        text = text.replace(unicode_char, krutidev_char)

    return text