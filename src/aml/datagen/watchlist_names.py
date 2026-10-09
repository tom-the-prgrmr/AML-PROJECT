"""Static, synthetic name lists for the watchlist generator (Latin uppercase ASCII only).

Names of Russian, Arabic and Chinese origin are stored as tuples of transliteration
variants: the first variant is the primary spelling, the others are alternative
romanisations (e.g. ``MUHAMMAD`` / ``MOHAMMED``, ``ZHANG`` / ``CHANG``). Every tuple has
at least two variants so that each such entry can carry a differing alias.
"""

from __future__ import annotations

Variants = tuple[str, ...]

RU_GIVEN: list[Variants] = [
    ("ALEKSANDR", "ALEXANDER", "ALEKSANDER"),
    ("SERGEI", "SERGEY", "SERGUEI"),
    ("DMITRII", "DMITRY", "DMITRI"),
    ("NIKOLAI", "NIKOLAY", "NICOLAI"),
    ("VLADIMIR", "WLADIMIR", "VLADIMER"),
    ("ANDREI", "ANDREY", "ANDRE"),
    ("YURII", "YURI", "IURII"),
    ("EVGENII", "YEVGENY", "EUGENE"),
    ("ALEKSEI", "ALEXEY", "ALEXEI"),
    ("MIKHAIL", "MIHAIL", "MICHAEL"),
    ("IGOR", "IHOR"),
    ("OLEG", "OLEGH"),
    ("VIKTOR", "VICTOR"),
    ("PAVEL", "PAVLO", "PAUL"),
    ("ANASTASIIA", "ANASTASIYA", "ANASTASIA"),
    ("EKATERINA", "YEKATERINA", "CATHERINE"),
    ("TATIANA", "TATYANA", "TATIANNA"),
    ("ELENA", "YELENA", "HELENA"),
]
RU_SURNAME: list[Variants] = [
    ("IVANOV", "IVANOFF"),
    ("PETROV", "PETROFF"),
    ("SMIRNOV", "SMIRNOFF"),
    ("KUZNETSOV", "KUZNETSOFF", "KOUZNETSOV"),
    ("POPOV", "POPOFF"),
    ("VOLKOV", "WOLKOW"),
    ("SOKOLOV", "SOKOLOFF"),
    ("LEBEDEV", "LEBEDEFF"),
    ("KOZLOV", "KOZLOFF"),
    ("NOVIKOV", "NOVIKOFF"),
    ("MOROZOV", "MOROZOFF"),
    ("ZAKHAROV", "ZAHAROV", "SAKHAROV"),
    ("BELYAKOV", "BELIAKOV"),
    ("GORBUNOV", "GORBOUNOV"),
    ("TITOV", "TITOFF"),
    ("ORLOV", "ORLOFF"),
]

AR_GIVEN: list[Variants] = [
    ("MUHAMMAD", "MOHAMMED", "MOHAMED"),
    ("AHMAD", "AHMED"),
    ("ABDULLAH", "ABDALLAH", "ABDULLA"),
    ("HUSSEIN", "HUSAIN", "HUSSAIN"),
    ("OMAR", "UMAR"),
    ("YUSUF", "YOUSSEF", "YUSEF"),
    ("IBRAHIM", "EBRAHIM"),
    ("KHALID", "KHALED"),
    ("MAHMUD", "MAHMOUD"),
    ("SALEH", "SALIH"),
    ("HASSAN", "HASAN"),
    ("FATIMA", "FATIMAH"),
    ("AISHA", "AYSHA", "AICHA"),
    ("ABDUL RAHMAN", "ABD AL RAHMAN", "ABDURRAHMAN"),
    ("MUSTAFA", "MUSTAPHA"),
    ("TARIQ", "TARIK"),
]
AR_FAMILY: list[Variants] = [
    ("AL HUSSEINI", "EL HUSSEINI"),
    ("AL RASHID", "AR RASHID"),
    ("AL SAYEGH", "EL SAYEGH"),
    ("AL MASRI", "EL MASRI"),
    ("AL TIKRITI", "EL TIKRITI"),
    ("KHOURY", "KHOURI"),
    ("HAMDAN", "HAMDANE"),
    ("NASSER", "NASIR"),
    ("AL QADI", "EL KADI"),
    ("HADDAD", "HADDADI"),
    ("MANSOUR", "MANSUR"),
    ("AL SHAMI", "ASH SHAMI"),
]

ZH_SURNAME: list[Variants] = [
    ("ZHANG", "CHANG"),
    ("WANG", "WONG"),
    ("LI", "LEE"),
    ("LIU", "LAU"),
    ("CHEN", "CHAN"),
    ("YANG", "YEUNG"),
    ("ZHAO", "CHAO"),
    ("HUANG", "WONG"),
    ("ZHOU", "CHOU"),
    ("WU", "NG"),
    ("XU", "HSU"),
    ("SUN", "SUEN"),
    ("MA", "MAH"),
    ("ZHU", "CHU"),
    ("HU", "WOO"),
    ("GUO", "KWOK"),
]
ZH_GIVEN: list[Variants] = [
    ("WEI", "WAI"),
    ("JUN", "CHUN"),
    ("XIAOMING", "HSIAO MING"),
    ("JIANHUA", "CHIEN HUA"),
    ("QIANG", "CHIANG"),
    ("LEI", "LAY"),
    ("YONG", "YUNG"),
    ("PING", "PIN"),
    ("MEILING", "MEI LING"),
    ("XIUYING", "HSIU YING"),
    ("JIE", "CHIEH"),
    ("TAO", "TAU"),
    ("HONGBO", "HUNG PO"),
    ("YAN", "YEN"),
    ("FANG", "FONG"),
    ("GUOQIANG", "KUO CHIANG"),
]

# Names of "other" origin (single spelling; no transliteration requirement).
OTHER_GIVEN: list[str] = [
    "JOHN", "JAMES", "ROBERT", "MARIA", "CARLOS", "JOSE", "PEDRO", "HECTOR", "DAVID", "PETER",
    "SAMUEL", "ANA", "LUCIA", "JEAN", "PIERRE", "HANS", "KLAUS", "ALI", "REZA", "HOSSEIN",
    "KIM", "JONG", "AUNG", "SOE", "MIN", "KYAW",
]  # fmt: skip
OTHER_FAMILY: list[str] = [
    "SMITH", "JOHNSON", "GARCIA", "RODRIGUEZ", "MARTINEZ", "LOPEZ", "SCHMIDT", "MULLER",
    "DUBOIS", "MOREAU", "KARIMI", "HASHEMI", "MOUSAVI", "PARK", "CHOI", "JONG UN", "THAN",
    "HTUN", "NAING", "OKAFOR", "ADEYEMI",
]  # fmt: skip

# Origin -> candidate ISO-2 nationalities.
NATIONALITIES: dict[str, list[str]] = {
    "vi": ["VN"],
    "ru": ["RU", "BY", "KZ"],
    "ar": ["SA", "IQ", "SY", "LY", "YE", "AE", "EG", "JO"],
    "zh": ["CN", "TW", "HK"],
    "other": ["IR", "KP", "MM", "CU", "VE", "NG", "PK", "AF", "US", "FR"],
}

# Tokens that make a trap entry distinguishable from every real customer.
TRAP_DISTINGUISHERS: list[str] = [
    "KARIMOV", "VOLKANOV", "TSARENKO", "BASHIROV", "ZELINSKY", "MARKOVIC", "DJORDJEVIC",
    "HALVORSEN", "OKONKWO", "ABARCA", "QUINTERO", "SANDOVAL", "LINDQVIST", "PETROSYAN",
    "ABRAMOVICH", "TOLSTOY", "KASPAROV", "SHEVCHUK", "BRZEZINSKI", "NAKAMURO",
]  # fmt: skip

SANCTIONS_PROGRAMS: list[str] = ["SDGT", "UKRAINE-EO13662", "IRAN", "DPRK", "NARCOTICS", "CYBER"]
PEP_PROGRAMS: list[str] = ["PEP-DOMESTIC", "PEP-FOREIGN", "PEP-INTL-ORG", "PEP-FAMILY"]
