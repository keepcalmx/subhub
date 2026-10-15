"""节点名地区识别：用于自动地区分组"""
import re

# 顺序即优先级；短代码用 \b 防止误匹配（如 US 误中 RUSSIA）
REGION_PATTERNS = [
    ("香港", re.compile(r"香港|\bHK\b|Hong ?Kong|🇭🇰")),
    ("澳门", re.compile(r"澳门|\bMO\b|Maca[ou]|🇲🇴")),
    ("台湾", re.compile(r"台湾|台北|新北|彰化|\bTW\b|Taiwan|Hinet|🇹🇼")),
    ("日本", re.compile(r"日本|东京|大阪|埼玉|\bJP\b|Japan|🇯🇵")),
    ("韩国", re.compile(r"韩国|首尔|春川|\bKR\b|Korea|🇰🇷")),
    ("新加坡", re.compile(r"新加坡|狮城|\bSG\b|Singapore|🇸🇬")),
    ("美国", re.compile(r"美国|美西|美东|洛杉矶|圣何塞|西雅图|凤凰城|\bUS\b|United ?States|🇺🇸")),
    ("加拿大", re.compile(r"加拿大|多伦多|温哥华|\bCA\b|Canada|🇨🇦")),
    ("墨西哥", re.compile(r"墨西哥|Mexico|🇲🇽")),
    ("巴西", re.compile(r"巴西|Brazil|🇧🇷")),
    ("阿根廷", re.compile(r"阿根廷|Argentina|🇦🇷")),
    ("英国", re.compile(r"英国|伦敦|\bUK\b|\bGB\b|United ?Kingdom|London|🇬🇧")),
    ("德国", re.compile(r"德国|法兰克福|\bDE\b|Germany|Frankfurt|🇩🇪")),
    ("法国", re.compile(r"法国|巴黎|\bFR\b|France|Paris|🇫🇷")),
    ("荷兰", re.compile(r"荷兰|阿姆斯特丹|\bNL\b|Netherlands|Amsterdam|🇳🇱")),
    ("土耳其", re.compile(r"土耳其|伊斯坦布尔|\bTR\b|Turkey|Istanbul|🇹🇷")),
    ("俄罗斯", re.compile(r"俄罗斯|莫斯科|RUSSIA|Russia|🇷🇺")),
    ("印度", re.compile(r"印度|孟买|\bIN\b|India|Mumbai|🇮🇳")),
    ("澳大利亚", re.compile(r"澳大利亚|澳洲|悉尼|\bAU\b|Australia|Sydney|🇦🇺")),
    ("马来西亚", re.compile(r"马来西亚|\bMY\b|Malaysia|🇲🇾")),
    ("泰国", re.compile(r"泰国|曼谷|\bTH\b|Thailand|🇹🇭")),
    ("越南", re.compile(r"越南|\bVN\b|Vietnam|🇻🇳")),
    ("菲律宾", re.compile(r"菲律宾|\bPH\b|Philippines|🇵🇭")),
    ("印尼", re.compile(r"印尼|印度尼西亚|雅加达|Indonesia|🇮🇩")),
    ("瑞士", re.compile(r"瑞士|Switzerland|🇨🇭")),
    ("瑞典", re.compile(r"瑞典|Sweden|🇸🇪")),
    ("西班牙", re.compile(r"西班牙|Spain|🇪🇸")),
    ("意大利", re.compile(r"意大利|Italy|🇮🇹")),
    ("乌克兰", re.compile(r"乌克兰|Ukraine|🇺🇦")),
    ("阿联酋", re.compile(r"阿联酋|迪拜|Dubai|🇦🇪")),
]


def detect(name: str):
    """返回节点所属地区名，未识别返回 None"""
    for region, pattern in REGION_PATTERNS:
        if pattern.search(name):
            return region
    return None
