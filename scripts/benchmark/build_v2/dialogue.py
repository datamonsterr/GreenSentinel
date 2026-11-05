"""Dialogue and report synthesizer for releases_v2 with high lexical variety, natural colloquialisms, and zero label leakage."""

from __future__ import annotations

import random
from typing import Any

_VI_DIACRITICS_MAP = {
    "à": "a",
    "á": "a",
    "ả": "a",
    "ã": "a",
    "ạ": "a",
    "ă": "a",
    "ằ": "a",
    "ắ": "a",
    "ẳ": "a",
    "ẵ": "a",
    "ặ": "a",
    "â": "a",
    "ầ": "a",
    "ấ": "a",
    "ẩ": "a",
    "ẫ": "a",
    "ậ": "a",
    "è": "e",
    "é": "e",
    "ẻ": "e",
    "ẽ": "e",
    "ẹ": "e",
    "ê": "e",
    "ề": "e",
    "ế": "e",
    "ể": "e",
    "ễ": "e",
    "ệ": "e",
    "ì": "i",
    "í": "i",
    "ỉ": "i",
    "ĩ": "i",
    "ị": "i",
    "ò": "o",
    "ó": "o",
    "ỏ": "o",
    "õ": "o",
    "ọ": "o",
    "ô": "o",
    "ồ": "o",
    "ố": "o",
    "ổ": "o",
    "ỗ": "o",
    "ộ": "o",
    "ơ": "o",
    "ờ": "o",
    "ớ": "o",
    "ở": "o",
    "ỡ": "o",
    "ợ": "o",
    "ù": "u",
    "ú": "u",
    "ủ": "u",
    "ũ": "u",
    "ụ": "u",
    "ư": "u",
    "ừ": "u",
    "ứ": "u",
    "ử": "u",
    "ữ": "u",
    "ự": "u",
    "ỳ": "y",
    "ý": "y",
    "ỷ": "y",
    "ỹ": "y",
    "ỵ": "y",
    "đ": "d",
    "À": "A",
    "Á": "A",
    "Ả": "A",
    "Ã": "A",
    "Ạ": "A",
    "Ă": "A",
    "Ằ": "A",
    "Ắ": "A",
    "Ẳ": "A",
    "Ẵ": "A",
    "Ặ": "A",
    "Â": "A",
    "Ầ": "A",
    "Ấ": "A",
    "Ẩ": "A",
    "Ẫ": "A",
    "Ậ": "A",
    "È": "E",
    "É": "E",
    "Ẻ": "E",
    "Ẽ": "E",
    "Ẹ": "E",
    "Ê": "E",
    "Ề": "E",
    "Ế": "E",
    "Ể": "E",
    "Ễ": "E",
    "Ệ": "E",
    "Ì": "I",
    "Í": "I",
    "Ỉ": "I",
    "Ĩ": "I",
    "Ị": "I",
    "Ò": "O",
    "Ó": "O",
    "Ỏ": "O",
    "Õ": "O",
    "Ọ": "O",
    "Ô": "O",
    "Ồ": "O",
    "Ố": "O",
    "Ổ": "O",
    "Ỗ": "O",
    "Ộ": "O",
    "Ơ": "O",
    "Ờ": "O",
    "Ớ": "O",
    "Ở": "O",
    "Ỡ": "O",
    "Ợ": "O",
    "Ù": "U",
    "Ú": "U",
    "Ủ": "U",
    "Ũ": "U",
    "Ụ": "U",
    "Ư": "U",
    "Ừ": "U",
    "Ứ": "U",
    "Ử": "U",
    "Ữ": "U",
    "Ự": "U",
    "Ỳ": "Y",
    "Ý": "Y",
    "Ỷ": "Y",
    "Ỹ": "Y",
    "Ỵ": "Y",
    "Đ": "D",
}


def strip_accents(text: str) -> str:
    """Strip Vietnamese diacritics to simulate unaccented mobile typing."""
    return "".join(_VI_DIACRITICS_MAP.get(c, c) for c in text)


# Colloquial prefixes & suffixes
_PREFIX_VI = (
    "",
    "Alo",
    "Dạ",
    "Vâng",
    "Bác tài ơi",
    "Anh ơi",
    "Em ơi",
    "Tài xế ơi",
    "Chào anh",
    "Chào bác",
    "Ơ",
    "Này",
    "Ừ",
    "À",
    "Phiền anh",
    "Ủa anh ơi",
    "Cho em hỏi xíu",
    "Bác ơi",
)

_PREFIX_EN = (
    "",
    "Hi",
    "Hello",
    "Hey driver",
    "Excuse me",
    "Look",
    "Well",
    "Uh",
    "Morning",
    "Quick question",
)

_SUFFIX_VI = (
    "",
    " ạ",
    " nhé anh",
    " nha",
    " giúp em",
    " với ạ",
    " nha bác",
    " luôn",
    " đấy ạ",
    " nhé",
    " nhe",
    " nha anh",
    " giùm em",
    " với",
    " nè",
)

_SUFFIX_EN = (
    "",
    " please",
    " thanks",
    " though",
    " ok",
    " mate",
    " thank you",
    " appreciated",
)

_PUNCT = (".", "!", "...", "", "?")

# Natural small talk conversations (weather, AC, music, luggage)
_IRRELEVANT_CONVERSATIONS = [
    [
        {"role": "customer", "text": "Bác tài bật giùm em máy lạnh mát chút nha", "lang": "vi"},
        {"role": "driver", "text": "Dạ vâng xe đang bật số 2 rồi em nhé", "lang": "vi"},
    ],
    [
        {"role": "customer", "text": "Xe mình có cốp để vali cỡ vừa không anh?", "lang": "vi"},
        {"role": "driver", "text": "Cốp rộng thoải mái em, cứ để anh phụ bê", "lang": "vi"},
    ],
    [
        {"role": "customer", "text": "Trời mưa to quá anh nhỉ", "lang": "vi"},
        {"role": "driver", "text": "Vâng mưa ngập một vài đoạn nên em đi cẩn thận", "lang": "vi"},
    ],
    [
        {"role": "customer", "text": "Hi driver, can you turn up the AC a bit?", "lang": "en"},
        {"role": "driver", "text": "Sure, already set to cool mode", "lang": "en"},
    ],
    [
        {"role": "customer", "text": "I have one small backpack with me", "lang": "en"},
        {"role": "driver", "text": "No problem at all, see you shortly", "lang": "en"},
    ],
    [
        {"role": "customer", "text": "Bác tài chạy êm quá em cảm ơn", "lang": "vi"},
        {"role": "driver", "text": "Dạ cảm ơn em, chúc em ngày mới tốt lành", "lang": "vi"},
    ],
]

# Natural misunderstandings without fraud leakage
_CONTRADICTORY_CONVERSATIONS = [
    [
        {"role": "customer", "text": "Tôi đang đứng ngay sảnh chính cổng số 1", "lang": "vi"},
        {"role": "driver", "text": "Ủa anh đỗ ở cổng 1 nãy giờ không thấy ai", "lang": "vi"},
    ],
    [
        {"role": "driver", "text": "Em tới nơi rồi nha anh mặc áo đen", "lang": "vi"},
        {"role": "customer", "text": "Ủa tôi đứng ở điểm ghim từ nãy không thấy xe nào cả", "lang": "vi"},
    ],
    [
        {"role": "customer", "text": "I am waiting right outside the lobby entrance", "lang": "en"},
        {"role": "driver", "text": "I am in front of the lobby entrance right now too", "lang": "en"},
    ],
]

# Conversational messages pool (Vietnamese first ~65%, English ~35%)
_MESSAGES_POOL: dict[str, dict[str, list[dict[str, str]]]] = {
    "normal": {
        "customer": [
            {"text": "Em đang đứng trước cửa sảnh", "lang": "vi"},
            {"text": "Em mặc áo sơ mi trắng quần tây nhé", "lang": "vi"},
            {"text": "Bác tài tới nơi cứ nháy máy em", "lang": "vi"},
            {"text": "Em chuẩn bị xuống cầu thang rồi ạ", "lang": "vi"},
            {"text": "Em ra ngay đây rồi bác tài chờ em 1 phút", "lang": "vi"},
            {"text": "Em đứng ở chân tòa nhà gần cây xăng nha", "lang": "vi"},
            {"text": "I am waiting by the pickup pin", "lang": "en"},
            {"text": "Wearing a blue jacket outside the entrance", "lang": "en"},
            {"text": "Stepping out the elevator right now", "lang": "en"},
            {"text": "Standing near the coffee shop beside the gate", "lang": "en"},
        ],
        "driver": [
            {"text": "Dạ em đang tới, khoảng 2-3 phút nữa", "lang": "vi"},
            {"text": "Xe em màu bạc đậu gần bảo vệ nhé", "lang": "vi"},
            {"text": "Vâng em đang rẽ vào ngõ rồi ạ", "lang": "vi"},
            {"text": "Em bật đèn khẩn cấp đỗ trước sảnh rồi nhé", "lang": "vi"},
            {"text": "Dạ em thấy bạn rồi, đang táp vào lề", "lang": "vi"},
            {"text": "On my way, arriving in a couple of minutes", "lang": "en"},
            {"text": "Car hazard lights are on near the lobby", "lang": "en"},
            {"text": "I have arrived at the pickup spot", "lang": "en"},
        ],
    },
    "honest_traffic": {
        "customer": [
            {"text": "Bác tài ơi ngã tư phía trước đông lắm không", "lang": "vi"},
            {"text": "Thấy xe di chuyển hơi chậm xíu", "lang": "vi"},
            {"text": "Hôm nay giờ cao điểm tắc đường quá anh nhỉ", "lang": "vi"},
            {"text": "Traffic looks heavy around here", "lang": "en"},
            {"text": "Is the junction jammed up ahead?", "lang": "en"},
        ],
        "driver": [
            {"text": "Đoạn này đang kẹt cứng xe nhích từng mét em thông cảm", "lang": "vi"},
            {"text": "Đèn đỏ ở đây đang tắc dài quá em chờ xíu nhé", "lang": "vi"},
            {"text": "Đường đang thi công rào chắn nên phải đi chậm", "lang": "vi"},
            {"text": "Xe container chết máy chắn lối nên xe dồn ứ lại", "lang": "vi"},
            {"text": "Heavy traffic jam ahead, crawling slowly", "lang": "en"},
            {"text": "Road construction narrowed the lane, waiting it out", "lang": "en"},
        ],
    },
    "stall": {
        "customer": [
            {"text": "Bác tài ơi sao xe đứng yên nãy giờ chưa qua?", "lang": "vi"},
            {"text": "Anh có qua đón được không để em biết?", "lang": "vi"},
            {"text": "Em đứng chờ lâu rồi mà xe chưa chạy tới", "lang": "vi"},
            {"text": "Nếu không đón được thì báo em một tiếng nhé", "lang": "vi"},
            {"text": "Thấy xe đỗ ở đoạn ngã tư từ nãy", "lang": "vi"},
            {"text": "The car hasn't moved for several minutes", "lang": "en"},
            {"text": "Are you still coming to pick me up?", "lang": "en"},
            {"text": "Let me know if there is an issue", "lang": "en"},
        ],
        "driver": [
            {"text": "Em đang vướng chút việc gấp", "lang": "vi"},
            {"text": "Xe em đang trục trặc máy chưa chạy được", "lang": "vi"},
            {"text": "Đường đông quá chưa nhích được bạn ơi", "lang": "vi"},
            {"text": "Đang bị kẹt trong bãi đỗ xe xíu", "lang": "vi"},
            {"text": "Having some unexpected vehicle trouble", "lang": "en"},
            {"text": "Stuck at parking lot exit gate", "lang": "en"},
        ],
    },
    "deviation": {
        "customer": [
            {"text": "Bác tài rẽ lối này đi đâu thế anh?", "lang": "vi"},
            {"text": "Hình như rẽ nhầm đường rồi, lối kia gần hơn mà", "lang": "vi"},
            {"text": "Sao xe đi đường khác bản đồ vậy anh?", "lang": "vi"},
            {"text": "Lối này em thấy hơi xa điểm đến đó", "lang": "vi"},
            {"text": "You missed the turn back there", "lang": "en"},
            {"text": "Why are we taking this back road?", "lang": "en"},
            {"text": "Isn't the direct road faster?", "lang": "en"},
        ],
        "driver": [
            {"text": "Đường kia đang cấm nên em phải chạy vòng", "lang": "vi"},
            {"text": "Bản đồ chỉ lối này thông thoáng hơn em nhé", "lang": "vi"},
            {"text": "Em đang quay đầu ở ngã tư tiếp theo", "lang": "vi"},
            {"text": "Đoạn trên đang ngập nước nên anh né ra", "lang": "vi"},
            {"text": "Taking a detour to avoid roadworks", "lang": "en"},
            {"text": "Will make a U-turn at the next intersection", "lang": "en"},
        ],
    },
    "technical_dropout": {
        "customer": [
            {"text": "Alo bác tài ơi, mạng bị chập chờn hả anh", "lang": "vi"},
            {"text": "App vừa báo mất kết nối vị trí", "lang": "vi"},
            {"text": "Tự nhiên bản đồ không tải được vị trí xe", "lang": "vi"},
            {"text": "Map stopped updating the location", "lang": "en"},
            {"text": "Network connection dropped on the map", "lang": "en"},
        ],
        "driver": [
            {"text": "Mạng 4G của em chập chờn quá đang mất sóng", "lang": "vi"},
            {"text": "Điện thoại em vừa bị sập nguồn khởi động lại", "lang": "vi"},
            {"text": "Qua đoạn hầm nên mất tín hiệu điện thoại", "lang": "vi"},
            {"text": "Lost cellular connection temporarily in the tunnel", "lang": "en"},
        ],
    },
    "phantom": {
        "customer": [
            {"text": "Ủa tôi đứng ở sảnh chưa thấy xe mà?", "lang": "vi"},
            {"text": "Anh ơi đón ai vậy, tôi vẫn đứng ở điểm hẹn", "lang": "vi"},
            {"text": "Sao app báo đón khách rồi tôi chưa lên xe?", "lang": "vi"},
            {"text": "Bác tài đón nhầm người rồi à", "lang": "vi"},
            {"text": "The trip shows started but nobody picked me up", "lang": "en"},
            {"text": "I am still waiting at the main entrance", "lang": "en"},
            {"text": "Did you pick up the wrong passenger?", "lang": "en"},
        ],
        "driver": [
            {"text": "Ủa em tưởng bạn khách vừa lên là người đặt", "lang": "vi"},
            {"text": "Dạ em đang chạy rồi ạ", "lang": "vi"},
            {"text": "Để em kiểm tra lại thông tin khách", "lang": "vi"},
            {"text": "Checking booking details now", "lang": "en"},
        ],
    },
    "teleport": {
        "customer": [
            {"text": "App định vị bị giật giật nhảy chỗ này chỗ khác", "lang": "vi"},
            {"text": "Bản đồ hiển thị xe lung tung quá anh ơi", "lang": "vi"},
            {"text": "Thấy xe trên app biến mất rồi hiện lại", "lang": "vi"},
            {"text": "The vehicle pin jumped across the screen", "lang": "en"},
            {"text": "Map location looks glitchy right now", "lang": "en"},
        ],
        "driver": [
            {"text": "Chắc GPS máy em bị lỗi bắt sóng", "lang": "vi"},
            {"text": "Tín hiệu điện thoại đang bị nhảy vị trí", "lang": "vi"},
            {"text": "Đi qua khu nhà cao tầng sóng định vị kém", "lang": "vi"},
            {"text": "GPS signal is bouncing between high rises", "lang": "en"},
        ],
    },
}

# Thematic pools of realistic customer complaints (shared across honest and fraud trips)
_COMPLAINTS_BY_THEME: dict[str, list[str]] = {
    "general": [
        "Máy lạnh trong xe hơi yếu thời tiết lại nóng",
        "Xe có mùi thuốc lá nồng làm người đi cùng bị say xe",
        "Tài xế thái độ hơi cộc cằn khi khách hỏi đường",
        "Bác tài lái xe hơi giật cục phanh gấp nhiều lần",
        "Cước phí chuyến đi cao hơn so với bình thường",
        "Xe chưa được dọn dẹp sạch sẽ có rác dưới sàn",
        "Tài xế bấm còi hơi nhiều trong khu dân cư",
        "Air conditioner was warm on a hot sunny day",
        "Driver was impatient and spoke rudely to passenger",
        "Car had a noticeable cigarette smell inside",
        "Rough driving with abrupt braking at red lights",
        "Fare charge seemed higher than the estimated range",
    ],
    "late_or_stall": [
        "Tài xế đến đón hơi muộn so với dự kiến",
        "Xe đón trễ gần 10 phút do tắc đường",
        "Đường kẹt xe nhiều đoạn di chuyển rất chậm chạp",
        "Xe đậu một chỗ nãy giờ không chịu di chuyển",
        "Chờ hơn 5 phút xe đứng im ở góc đường",
        "Đợi lâu quá sốt ruột mà xe không chạy đón khách",
        "Bác tài đứng yên không nhích dù đường thông thoáng",
        "Driver arrived 10 minutes later than estimated",
        "Traffic was congested and took much longer than expected",
        "Driver remained parked down the road and never moved",
        "Waited over 5 minutes while vehicle stayed stationary",
        "Car is not moving towards the pickup location",
    ],
    "detour": [
        "Tài xế chạy vào mấy ngõ ngách xa hơn lộ trình",
        "Bác tài rẽ nhầm đường làm chuyến đi kéo dài",
        "Sao đi đường vòng vèo tốn thêm tiền cước vậy",
        "Lái xe không đi đường lớn mà đi lối xa hơn",
        "Xe rẽ hướng khác làm tôi bị muộn giờ hẹn",
        "Driver took a roundabout route through narrow alleys",
        "Vehicle missed the main turn and took a longer way",
        "Unnecessarily long route resulted in extra travel time",
        "Driver turned in the opposite direction from the highway",
    ],
    "glitch": [
        "Định vị trên ứng dụng nhảy sang khu vực khác",
        "Bản đồ bị lỗi giật vị trí xe liên tục",
        "Thấy xe trên app biến mất rồi hiện lại ở vị trí xa",
        "Mất kết nối mạng với tài xế suốt chuyến đi",
        "App báo không nhận được tín hiệu từ xe",
        "Điện thoại tài xế mất sóng không gọi được",
        "Map display was glitching and vehicle pin jumped around",
        "App showed abnormal jumps in vehicle location",
        "Network connection lost during the journey",
        "App failed to receive telemetry signal from vehicle",
    ],
    "wrong_spot": [
        "Bác tài đậu nhầm bên kia đường làm tôi phải đi bộ qua",
        "Tài xế đỗ sai cổng đón khiến tôi tìm mãi mới thấy",
        "Tài xế đỗ xe cách điểm đón một đoạn không tới",
        "Car stopped across the busy street instead of the lobby pin",
        "Driver dropped off far from the requested entrance gate",
        "Driver stopped at a junction and ignored messages",
    ],
    "cancel_refusal": [
        "Tài xế vừa nhận cuốc xong huỷ luôn",
        "Đang đứng chờ thì tài xế tự ý bấm huỷ",
        "Bác tài gọi bảo tôi tự huỷ chuyến giùm vì bận",
        "Tài xế báo xe hết xăng không đón được rồi huỷ",
        "Chờ mấy phút tài xế huỷ ngang không đón",
        "Driver accepted the ride and cancelled shortly after",
        "Driver asked me to cancel the trip on my end",
        "Driver cancelled abruptly without showing up",
    ],
    "not_picked_up": [
        "Tôi đứng chờ mãi mà app báo chuyến đã hoàn thành",
        "Chưa lên xe mà tài xế đã bấm bắt đầu rồi kết thúc",
        "Bị trừ tiền cước dù thực tế không hề được đón",
        "Tôi vẫn ở sảnh đón mà app báo đã trả khách",
        "Tài xế đón ai khác hay sao mà hoàn thành chuyến của tôi",
        "Trip was marked completed while I was still waiting outside",
        "Charged for a ride that I never boarded",
        "App says completed but driver never showed up at pickup",
    ],
}


def vary_text(rng: random.Random, text: str, lang: str) -> str:
    prefixes = _PREFIX_EN if lang == "en" else _PREFIX_VI
    suffixes = _SUFFIX_EN if lang == "en" else _SUFFIX_VI
    p = rng.choice(prefixes)
    s = rng.choice(suffixes)
    punct = rng.choice(_PUNCT)
    core = f"{p} {text}".strip() if p else text
    res = f"{core}{s}{punct}".strip()

    # 15% probability of no-diacritic typing for Vietnamese
    if lang == "vi" and rng.random() < 0.15:
        res = strip_accents(res)
    return res


def vary_report(rng: random.Random, text: str) -> str:
    """Paraphrase customer report with natural variation and optional no-diacritic form."""
    punct = rng.choice(_PUNCT)
    res = f"{text}{punct}".strip()

    # 18% probability of no-diacritic typing (very common on mobile customer support)
    if rng.random() < 0.18:
        res = strip_accents(res)
    return res


def synthesize_realistic_dialogue(
    rng: random.Random,
    label: str,
    scenario: str,
    is_hard_negative: bool = False,
) -> list[dict[str, Any]]:
    # 45% of all trips have completely empty dialogue (very common in real rides)
    if rng.random() < 0.45:
        return []

    # 12% of trips have pleasant irrelevant conversation
    if rng.random() < 0.12:
        base_conv = rng.choice(_IRRELEVANT_CONVERSATIONS)
        turns = []
        offset = rng.randint(10, 40)
        for msg in base_conv:
            text = vary_text(rng, msg["text"], msg.get("lang", "vi"))
            turns.append(
                {
                    "role": msg["role"],
                    "text": text,
                    "sent_at_offset_s": offset,
                    "lang": msg.get("lang", "vi"),
                }
            )
            offset += rng.randint(15, 60)
        return turns

    # 6% of trips have contradictory misunderstanding
    if rng.random() < 0.06:
        base_conv = rng.choice(_CONTRADICTORY_CONVERSATIONS)
        turns = []
        offset = rng.randint(10, 40)
        for msg in base_conv:
            text = vary_text(rng, msg["text"], msg.get("lang", "vi"))
            turns.append(
                {
                    "role": msg["role"],
                    "text": text,
                    "sent_at_offset_s": offset,
                    "lang": msg.get("lang", "vi"),
                }
            )
            offset += rng.randint(15, 60)
        return turns

    # For remaining trips: 55% use standard normal pickup chat regardless of label
    if rng.random() < 0.55:
        pool_key = "normal"
    elif label == "ERR-02":
        pool_key = rng.choice(["stall", "honest_traffic", "normal"])
    elif label == "ERR-03":
        pool_key = rng.choice(["deviation", "normal"])
    elif label == "ERR-04":
        pool_key = rng.choice(["phantom", "normal", "stall"])
    elif label == "ERR-05":
        pool_key = rng.choice(["teleport", "normal", "technical_dropout"])
    elif label == "insufficient_evidence":
        pool_key = rng.choice(["technical_dropout", "teleport", "normal"])
    else:  # no_violation
        # Honest trips have traffic, detours, stalls, or glitches
        if is_hard_negative:
            pool_key = rng.choice(["honest_traffic", "stall", "deviation", "technical_dropout", "normal"])
        else:
            pool_key = "normal"

    pool = _MESSAGES_POOL.get(pool_key, _MESSAGES_POOL["normal"])
    n_turns = rng.randint(2, 5)
    turns = []
    current_role = rng.choice(["customer", "driver"])
    offset = rng.randint(5, 30)

    for _ in range(n_turns):
        role_msgs = pool.get(current_role, pool["customer"])
        chosen = rng.choice(role_msgs)
        text = vary_text(rng, chosen["text"], chosen.get("lang", "vi"))
        turns.append(
            {
                "role": current_role,
                "text": text,
                "sent_at_offset_s": offset,
                "lang": chosen.get("lang", "vi"),
            }
        )
        current_role = "driver" if current_role == "customer" else "customer"
        offset += rng.randint(10, 75)

    return turns


def synthesize_realistic_customer_report(
    rng: random.Random,
    label: str,
    weak_evidence: bool = False,
    config: Any = None,
) -> str | None:
    honest_rate = getattr(config, "customer_report_honest_rate", 0.18) if config else 0.18
    fraud_rate = getattr(config, "customer_report_fraud_rate", 0.45) if config else 0.45

    if label == "no_violation":
        if rng.random() >= honest_rate:
            return None
        # Honest trips have complaints across all themes (general, late/stall, detour, glitch, wrong spot)
        category = rng.choices(
            ["general", "late_or_stall", "detour", "glitch", "wrong_spot"],
            weights=[0.35, 0.25, 0.15, 0.15, 0.10],
            k=1,
        )[0]
    elif label == "insufficient_evidence":
        if rng.random() >= 0.28 or weak_evidence:
            return None
        category = rng.choices(
            ["glitch", "general", "late_or_stall"],
            weights=[0.45, 0.35, 0.20],
            k=1,
        )[0]
    elif label == "ERR-01":
        if rng.random() >= fraud_rate or weak_evidence:
            return None
        category = rng.choices(
            ["cancel_refusal", "late_or_stall", "general"],
            weights=[0.50, 0.30, 0.20],
            k=1,
        )[0]
    elif label == "ERR-02":
        if rng.random() >= fraud_rate or weak_evidence:
            return None
        category = rng.choices(
            ["late_or_stall", "general", "wrong_spot"],
            weights=[0.50, 0.30, 0.20],
            k=1,
        )[0]
    elif label == "ERR-03":
        if rng.random() >= fraud_rate or weak_evidence:
            return None
        category = rng.choices(
            ["detour", "general", "late_or_stall"],
            weights=[0.50, 0.30, 0.20],
            k=1,
        )[0]
    elif label == "ERR-04":
        if rng.random() >= fraud_rate or weak_evidence:
            return None
        category = rng.choices(
            ["not_picked_up", "wrong_spot", "general"],
            weights=[0.50, 0.30, 0.20],
            k=1,
        )[0]
    elif label == "ERR-05":
        if rng.random() >= fraud_rate or weak_evidence:
            return None
        category = rng.choices(
            ["glitch", "general", "late_or_stall"],
            weights=[0.50, 0.30, 0.20],
            k=1,
        )[0]
    else:
        return None

    pool = _COMPLAINTS_BY_THEME[category]
    base = rng.choice(pool)
    return vary_report(rng, base)


_DRIVER_OBJECTIONS_BY_THEME = {
    "traffic_or_gridlock": [
        "Kẹt xe giờ cao điểm không di chuyển kịp",
        "Đường tắc cứng cả tiếng không nhích được, không phải tôi cố tình đứng yên",
        "Kẹt xe ngập đường giờ tan tầm, tôi có nhắn khách rồi",
        "Nút giao thông đang ùn tắc nghiêm trọng, xe nhích từng mét",
        "Đường đông nghẽn xe di chuyển rất chậm",
        "Ùn tắc cục bộ trước cổng trường học giờ tan trường",
        "Heavy peak hour traffic could not reach pickup in time",
        "Gridlock on main road, barely moving due to congestion",
    ],
    "legit_detour": [
        "Đoạn đường đang sửa chữa rào chắn nên phải đi đường vòng",
        "Đường cũ bị chặn thi công cầu cống, tôi buộc phải rẽ lối khác",
        "Đường ngập nước sâu xe không đi qua được, phải vòng đường khác",
        "Tránh đoạn ngập nước nên đi vòng sang đường gom",
        "Đường tránh đi nhanh hơn đường chính đang kẹt cứng",
        "Có biển báo cấm ô tô theo giờ nên phải đi đường tránh",
        "Road construction blocked route, had to take alternate street",
        "Street flooded after heavy rain, detour required for safety",
    ],
    "technical_glitch_or_gps": [
        "Sóng GPS khu này chập chờn nhảy lung tung, điện thoại tôi bắt sóng yếu",
        "Máy bị mất tín hiệu định vị lúc qua hầm hoặc nhà cao tầng",
        "Điện thoại bị nóng máy tín hiệu định vị nhảy, tôi đi đúng đường",
        "Ứng dụng cập nhật vị trí bị lag chậm nhịp",
        "Mạng 4G bị rớt không tải được lộ trình di chuyển",
        "Ứng dụng tài xế bị treo tự thoát ra ngoài",
        "Vị trí định vị bị trôi do thời tiết nhiều mây âm u",
        "Phone GPS drifted near tall buildings, drove normally",
        "App connection dropped intermittently during trip",
    ],
    "customer_issues_or_rating": [
        "Khách gọi không nghe máy điểm đón quá đông không tìm thấy",
        "Khách đứng sai điểm hẹn nổ chuyến rồi huỷ",
        "Khách chấm sao vô lý dù tôi phục vụ chu đáo đúng giờ",
        "Khách đòi đi vào đường cấm tôi từ chối nên khách báo cáo",
        "Chờ khách ra quá lâu gọi điện không ai nhấc máy",
        "Tôi có đón khách đúng hẹn ở sảnh chính",
        "Khách đặt nhầm điểm đón rồi tự bấm huỷ chuyến",
        "Customer was unreachable at designated pickup location",
        "Passenger insisted on unauthorized dropoff point and gave bad rating",
    ],
    "vehicle_or_breakdown": [
        "Xe bị thủng lốp dọc đường đang phải ghé vá",
        "Xe bị hỏng hóc kỹ thuật trên đường đến điểm đón",
        "Có sự cố đột xuất về xe cộ xin phép hỗ trợ",
        "Xe bị chết máy giữa đường đang chờ thợ tới xem",
        "Minor vehicle mechanical issue occurred on the way",
        "Flat tire required immediate roadside assistance",
    ],
}


def synthesize_realistic_driver_objection(
    rng: random.Random,
    label: str,
    config: Any = None,
) -> dict[str, str] | None:
    rates = getattr(config, "driver_objection_rates", None) if config else None
    if rates and label in rates:
        prob = rates[label]
    else:
        default_rates = {
            "no_violation": 0.04,
            "insufficient_evidence": 0.20,
            "ERR-01": 0.45,
            "ERR-02": 0.50,
            "ERR-03": 0.40,
            "ERR-04": 0.35,
            "ERR-05": 0.40,
        }
        prob = default_rates.get(label, 0.0)

    if rng.random() >= prob:
        return None

    if label == "no_violation":
        category = rng.choices(
            [
                "traffic_or_gridlock",
                "legit_detour",
                "customer_issues_or_rating",
                "technical_glitch_or_gps",
                "vehicle_or_breakdown",
            ],
            weights=[0.30, 0.25, 0.25, 0.15, 0.05],
            k=1,
        )[0]
    elif label == "insufficient_evidence":
        category = rng.choices(
            ["technical_glitch_or_gps", "traffic_or_gridlock", "vehicle_or_breakdown"],
            weights=[0.50, 0.25, 0.25],
            k=1,
        )[0]
    elif label == "ERR-01":
        category = rng.choices(
            ["traffic_or_gridlock", "customer_issues_or_rating", "vehicle_or_breakdown"],
            weights=[0.40, 0.30, 0.30],
            k=1,
        )[0]
    elif label == "ERR-02":
        category = rng.choices(
            ["traffic_or_gridlock", "customer_issues_or_rating", "vehicle_or_breakdown"],
            weights=[0.45, 0.30, 0.25],
            k=1,
        )[0]
    elif label == "ERR-03":
        category = rng.choices(
            ["legit_detour", "traffic_or_gridlock", "customer_issues_or_rating"],
            weights=[0.50, 0.30, 0.20],
            k=1,
        )[0]
    elif label == "ERR-04":
        category = rng.choices(
            ["customer_issues_or_rating", "technical_glitch_or_gps", "traffic_or_gridlock"],
            weights=[0.50, 0.30, 0.20],
            k=1,
        )[0]
    elif label == "ERR-05":
        category = rng.choices(
            ["technical_glitch_or_gps", "traffic_or_gridlock", "legit_detour"],
            weights=[0.50, 0.30, 0.20],
            k=1,
        )[0]
    else:
        category = "traffic_or_gridlock"

    pool = _DRIVER_OBJECTIONS_BY_THEME[category]
    base = rng.choice(pool)
    text = vary_report(rng, base)
    return {"status": "present", "text": text}
