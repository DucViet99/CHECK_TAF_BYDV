"""
TAF Validator - Kiểm tra bản tin TAF theo:
  - Quyết định 1656/QĐ-CHK (10/8/2023, Cục HKVN), Chương IV (TAF, TAF AMD)
    và các Chương/Phụ lục liên quan (I, II, PL1-PL4)
  - ICAO Annex 3 / Doc 10157 (PANS-MET)

Bản này viết lại toàn bộ so với bản gốc để bám sát nội dung văn bản 1656 đã
được cung cấp (đối chiếu từng mục), tham khảo cấu trúc/ý tưởng UI của ứng
dụng "TAF Checker & Validator" (React/TS) nhưng KHÔNG sao chép các đoạn xử lý
đặc biệt (hard-code theo case cụ thể) có trong ứng dụng đó, vì một số quy tắc
ở đó không đúng với văn bản 1656, cụ thể đã sửa:

  1) BECMG và FM được phép cùng xuất hiện trong một bản tin TAF (xem ví dụ
     mục 3.2b Chương IV: "...BECMG 1606/1608 ... FM161230..."). Bản gốc cấm
     điều này -> ĐÃ SỬA (không còn coi là lỗi).
  2) Độ cao chân mây (hshshs) hợp lệ với MỌI giá trị 000-100 (bước 30m/100ft,
     đã làm tròn) - không bị giới hạn chỉ ở các mức 30/60/150/300/450m. Các
     mức 30/60/150/300/450m (và 800/1500/3000m theo VFR) chỉ là NGƯỠNG để
     quyết định có phải đưa vào nhóm BECMG/TEMPO/FM hay không (mục 3.3d
     Chương IV), không phải là điều kiện định dạng của trị số độ cao mây.
     Bản gốc nhầm ngưỡng biến đổi thành điều kiện định dạng -> ĐÃ SỬA.
  3) Thời gian phát hành TAF: "không sớm hơn 1 giờ và không muộn hơn 30 phút
     so với giờ bắt đầu hiệu lực" (Chương IV, mục 1) -> cửa sổ hợp lệ là
     [start-60min, start+30min]. Bản gốc dùng nhầm 60 phút cho cả hai chiều
     -> ĐÃ SỬA.
  4) Danh sách mã hiện tượng thời tiết (w'w') được kiểm tra bằng NGỮ PHÁP
     (intensity/vicinity + descriptor + phenomena, theo Bảng 1-3/1-4 Chương I
     và mục 2.5 Chương IV) thay cho một whitelist cứng và thiếu (bản gốc
     thiếu rất nhiều tổ hợp hợp lệ như MIFG, BCFG, VCTS, BLSN, TSGR...).
  5) Bổ sung kiểm tra: PROB không được dùng với BECMG hoặc với FM (mục 3.1
     Chương IV: "Không sử dụng nhóm xác suất PROB với BECMG hay nhóm chỉ thị
     thời gian FMYYGGgg"); CAVOK không đi kèm hiện tượng thời tiết/mây CB-TCU
     (mục 2.4 Chương IV); tương quan VIS với FG/BR/HZ/FU/DU/SA theo Chương I
     mục 2.6 (và Lưu ý cuối mục đó); ngưỡng biến đổi gió/VIS/mây cho
     BECMG/TEMPO/FM theo mục 3.3 Chương IV; TEMPO/BECMG bắt buộc có khung
     thời gian YYGG/YeYeGeGe; FM bắt buộc dạng FMYYGGgg 6 chữ số.

API giữ nguyên để tương thích với app.py: quick_validate(taf_string) -> dict
với các khoá 'valid', 'errors', 'warnings', 'metadata', 'summary'.
"""

import re
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Dict, List, Optional


class ValidationErrorType(Enum):
    """Mức độ nghiêm trọng"""
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class ValidationError:
    """Một lỗi/cảnh báo, có gợi ý sửa (suggestion) như trong ứng dụng tham khảo"""
    stage: str
    error_type: ValidationErrorType
    message: str = ""
    group: Optional[str] = None
    regulation_ref: Optional[str] = None
    suggestion: Optional[str] = None


# ---------------------------------------------------------------------------
# Danh sách sân bay Việt Nam (theo 1656 & danh mục sân bay dân dụng hiện hành)
# ---------------------------------------------------------------------------
VIETNAM_AIRPORTS: Dict[str, Dict[str, str]] = {
    "VVNB": {"name": "Sân bay Quốc tế Nội Bài", "location": "Hà Nội"},
    "VVTS": {"name": "Sân bay Quốc tế Tân Sơn Nhất", "location": "TP. Hồ Chí Minh"},
    "VVDN": {"name": "Sân bay Quốc tế Đà Nẵng", "location": "Đà Nẵng"},
    "VVCR": {"name": "Sân bay Quốc tế Cam Ranh", "location": "Khánh Hòa"},
    "VVPQ": {"name": "Sân bay Quốc tế Phú Quốc", "location": "Kiên Giang"},
    "VVCI": {"name": "Sân bay Quốc tế Cát Bi", "location": "Hải Phòng"},
    "VVCT": {"name": "Sân bay Quốc tế Cần Thơ", "location": "Cần Thơ"},
    "VVPB": {"name": "Sân bay Quốc tế Phú Bài", "location": "Thừa Thiên Huế"},
    "VVVH": {"name": "Sân bay Quốc tế Vinh", "location": "Nghệ An"},
    "VVDL": {"name": "Sân bay Quốc tế Liên Khương", "location": "Lâm Đồng"},
    "VVVD": {"name": "Sân bay Quốc tế Vân Đồn", "location": "Quảng Ninh"},
    "VVCA": {"name": "Sân bay Chu Lai", "location": "Quảng Nam"},
    "VVTX": {"name": "Sân bay Thọ Xuân", "location": "Thanh Hóa"},
    "VVDB": {"name": "Sân bay Điện Biên Phủ", "location": "Điện Biên"},
    "VVDH": {"name": "Sân bay Đồng Hới", "location": "Quảng Bình"},
    "VVPC": {"name": "Sân bay Phù Cát", "location": "Bình Định"},
    "VVTH": {"name": "Sân bay Tuy Hòa", "location": "Phú Yên"},
    "VVBM": {"name": "Sân bay Buôn Ma Thuột", "location": "Đắk Lắk"},
    "VVPK": {"name": "Sân bay Pleiku", "location": "Gia Lai"},
    "VVCM": {"name": "Sân bay Cà Mau", "location": "Cà Mau"},
    "VVCS": {"name": "Sân bay Côn Đảo", "location": "Bà Rịa - Vũng Tàu"},
    "VVRG": {"name": "Sân bay Rạch Giá", "location": "Kiên Giang"},
}

# ---------------------------------------------------------------------------
# Ngữ pháp hiện tượng thời tiết w'w' (Bảng 1-3, 1-4 Chương I; mục 2.5 Chương IV)
# ---------------------------------------------------------------------------
DESCRIPTORS = ["MI", "BC", "PR", "DR", "BL", "SH", "FZ", "TS"]
PRECIP = ["DZ", "RA", "SN", "SG", "PL", "GR", "GS", "UP"]
OBSCURATION = ["FG", "BR", "SA", "DU", "HZ", "FU", "VA"]
OTHER_PHENOM = ["PO", "SQ", "FC", "DS", "SS"]
ALL_PHENOM = PRECIP + OBSCURATION + OTHER_PHENOM

_PHENOM_ALT = "|".join(sorted(ALL_PHENOM, key=len, reverse=True))
_DESC_ALT = "|".join(DESCRIPTORS)

# [VC] [+/-] [descriptor] phenomena{1,3}   (VC không kèm intensity)
WEATHER_RE = re.compile(
    rf"^(VC)?([+-])?((?:{_DESC_ALT}))?((?:{_PHENOM_ALT}){{1,3}})$"
)

# Ngưỡng thay đổi dùng cho BECMG/TEMPO/FM (mục 3.3 Chương IV)
VIS_CHANGE_THRESHOLDS = [150, 350, 600, 800, 1500, 3000, 5000]
CLOUD_HEIGHT_THRESHOLDS_FT = [1, 2, 5, 10, 15]  # 100/200/500/1000/1500 ft ~ 30/60/150/300/450m
ELIGIBLE_CHANGE_WX_TOKENS = {
    "FZFG", "FZRA", "FZDZ",
    "BLDU", "BLSA", "BLSN", "DRDU", "DRSA", "DRSN",
    "SQ", "FC", "DS", "SS",
}


class TAFValidator:
    """Bộ kiểm tra TAF, chia theo 4 giai đoạn (giữ cấu trúc bản gốc)."""

    def __init__(self, taf_string: str):
        self.raw_taf = taf_string.strip()
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []
        self.is_valid = False
        self.metadata: Dict = {}

    # ------------------------------------------------------------------
    def validate(self) -> Dict:
        try:
            self._stage1_format_validation()
            if not self._has_fatal():
                self._stage2_temporal_validation()
            if not self._has_fatal():
                self._stage3_meteorological_validation()
            if not self._has_fatal():
                self._stage4_consistency_checks()

            self.is_valid = len(
                [e for e in self.errors if e.error_type == ValidationErrorType.ERROR]
            ) == 0
        except Exception as e:  # pragma: no cover - an toàn khi có input lạ
            self.errors.append(ValidationError(
                stage="FATAL",
                error_type=ValidationErrorType.FATAL,
                message=f"Lỗi không xác định khi phân tích TAF: {e}",
            ))
            self.is_valid = False

        return self._generate_report()

    def _has_fatal(self) -> bool:
        return any(e.error_type == ValidationErrorType.FATAL for e in self.errors)

    # ------------------------------------------------------------------
    # STAGE 1: Cấu trúc & cú pháp (mục 2.1-2.7, 2.10 Chương IV)
    # ------------------------------------------------------------------
    def _stage1_format_validation(self):
        text = re.sub(r"\s+", " ", self.raw_taf).strip()
        ends_with_equal = text.endswith("=")
        if ends_with_equal:
            text = text[:-1].strip()
        self.metadata["ends_with_equal"] = ends_with_equal

        tokens = text.split(" ") if text else []
        if not tokens:
            self._add_error("STAGE1", "Không có nội dung TAF", ValidationErrorType.FATAL)
            return

        idx = 0
        taf_type = "TAF"
        if tokens[idx] != "TAF":
            self._add_error(
                "STAGE1", f"Bản tin phải bắt đầu bằng 'TAF', hiện là '{tokens[idx]}'.",
                ValidationErrorType.FATAL, "1656-IV.2.2",
                "Thêm 'TAF' vào đầu bản tin (hoặc 'TAF AMD'/'TAF COR' nếu là bản tin điều chỉnh/sửa lỗi).",
            )
            return
        idx += 1
        if idx < len(tokens) and tokens[idx] in ("AMD", "COR"):
            taf_type = f"TAF {tokens[idx]}"
            idx += 1

        # ICAO
        icao = tokens[idx] if idx < len(tokens) else ""
        if not re.match(r"^[A-Z]{4}$", icao):
            self._add_error(
                "STAGE1", f"Mã địa danh ICAO '{icao}' không hợp lệ (phải là 4 chữ in hoa).",
                ValidationErrorType.FATAL, "1656-IV.2.2",
            )
            return
        if icao not in VIETNAM_AIRPORTS:
            self._add_warning(
                "STAGE1",
                f"Mã ICAO '{icao}' không thuộc danh sách sân bay Việt Nam theo 1656/QĐ-CHK "
                f"(có thể vẫn hợp lệ nếu là TAF sân bay nước ngoài).",
                ValidationErrorType.WARNING, "1656-IV.2.2",
            )
        idx += 1

        # Issue time YYGGggZ
        issue_time = tokens[idx] if idx < len(tokens) else ""
        if not re.match(r"^\d{6}Z$", issue_time):
            self._add_error(
                "STAGE1", f"Thời gian phát hành '{issue_time}' sai định dạng (phải là YYGGggZ, ví dụ 122300Z).",
                ValidationErrorType.FATAL, "1656-IV.2.2",
            )
            return
        idx += 1

        # Validity Y1Y1G1G1/Y2Y2G2G2
        validity = tokens[idx] if idx < len(tokens) else ""
        if not re.match(r"^\d{4}/\d{4}$", validity):
            self._add_error(
                "STAGE1", f"Thời gian hiệu lực '{validity}' sai định dạng (phải là YYGG/YYGG, ví dụ 1300/1324).",
                ValidationErrorType.FATAL, "1656-IV.2.2",
            )
            return
        idx += 1

        self.metadata["taf_type"] = taf_type
        self.metadata["icao"] = icao
        self.metadata["airport"] = VIETNAM_AIRPORTS.get(
            icao, {"name": "Sân bay không xác định", "location": "?"}
        )
        self.metadata["issue_time"] = issue_time
        self.metadata["validity_period"] = validity

        d1, h1 = int(validity[0:2]), int(validity[2:4])
        d2, h2 = int(validity[5:7]), int(validity[7:9])
        if not (1 <= d1 <= 31 and 0 <= h1 <= 24):
            self._add_error("STAGE1", f"Ngày/giờ bắt đầu hiệu lực '{validity[:4]}' không hợp lệ.",
                             ValidationErrorType.ERROR, "1656-IV.2.2")
        if not (1 <= d2 <= 31 and 0 <= h2 <= 24):
            self._add_error("STAGE1", f"Ngày/giờ kết thúc hiệu lực '{validity[5:]}' không hợp lệ.",
                             ValidationErrorType.ERROR, "1656-IV.2.2")

        # Nếu là TAF COR: không được thay đổi nội dung khí tượng — chỉ cảnh báo nhắc
        if taf_type == "TAF COR":
            self._add_warning(
                "STAGE1",
                "TAF COR chỉ dùng để sửa lỗi cú pháp, không được thay đổi nội dung khí tượng so với TAF gốc.",
                ValidationErrorType.INFO, "1656-IV.1",
            )

        self._parse_groups(tokens[idx:])

    def _parse_groups(self, tokens: List[str]):
        """Chia TAF thành nhóm chính (BASE) và các nhóm biến đổi BECMG/TEMPO/FM,
        có thể có PROB30/PROB40 đứng trước TEMPO hoặc trước 1 nhóm giá trị."""
        groups: List[Dict] = []
        current: Dict = {"type": "BASE", "name": "BASE", "tokens": [], "prob": None, "time": None}

        i = 0
        n = len(tokens)
        while i < n:
            tok = tokens[i]

            if re.match(r"^PROB(\d{2})$", tok):
                prob_val = int(re.match(r"^PROB(\d{2})$", tok).group(1))
                if prob_val not in (30, 40):
                    self._add_error(
                        "STAGE1", f"Xác suất '{tok}' không hợp lệ. Chỉ dùng PROB30 hoặc PROB40.",
                        ValidationErrorType.ERROR, "1656-IV.3.1",
                        "Sửa thành PROB30 hoặc PROB40.",
                    )
                # Nhóm mới có thể là PROB+TEMPO hoặc PROB đứng riêng trước value-group
                groups.append(current)
                nxt = tokens[i + 1] if i + 1 < n else ""
                if nxt == "TEMPO":
                    current = {"type": "TEMPO", "name": f"PROB{prob_val} TEMPO", "tokens": [],
                               "prob": prob_val, "time": None}
                    i += 2
                else:
                    current = {"type": "PROB", "name": f"PROB{prob_val}", "tokens": [],
                               "prob": prob_val, "time": None}
                    i += 1
                if i < n and re.match(r"^\d{4}/\d{4}$", tokens[i]):
                    current["time"] = tokens[i]
                    i += 1
                else:
                    self._add_error(
                        "STAGE1", f"Nhóm '{current['name']}' thiếu khung thời gian YYGG/YeYeGeGe.",
                        ValidationErrorType.ERROR, "1656-IV.3",
                        "Thêm khung thời gian, ví dụ '1310/1316' ngay sau PROB/TEMPO.",
                    )
                continue

            if tok in ("BECMG", "TEMPO"):
                groups.append(current)
                current = {"type": tok, "name": tok, "tokens": [], "prob": None, "time": None}
                i += 1
                if i < n and re.match(r"^\d{4}/\d{4}$", tokens[i]):
                    current["time"] = tokens[i]
                    current["name"] = f"{tok} {tokens[i]}"
                    i += 1
                else:
                    self._add_error(
                        "STAGE1", f"Nhóm '{tok}' thiếu khung thời gian YYGG/YeYeGeGe.",
                        ValidationErrorType.ERROR, "1656-IV.3",
                        f"Thêm khung thời gian ngay sau '{tok}', ví dụ '{tok} 1310/1316'.",
                    )
                continue

            m_fm = re.match(r"^FM(\d{6})$", tok)
            if m_fm:
                groups.append(current)
                current = {"type": "FM", "name": tok, "tokens": [], "prob": None,
                           "time": m_fm.group(1)}
                i += 1
                continue
            if tok == "FM":
                # Dạng "FM YYGGgg" cách nhau bởi dấu cách (ít gặp nhưng chấp nhận được)
                groups.append(current)
                nxt = tokens[i + 1] if i + 1 < n else ""
                if re.match(r"^\d{6}$", nxt):
                    current = {"type": "FM", "name": f"FM{nxt}", "tokens": [], "prob": None, "time": nxt}
                    i += 2
                else:
                    self._add_error("STAGE1", "FM sai định dạng, phải là FMYYGGgg (6 chữ số liền).",
                                     ValidationErrorType.ERROR, "1656-IV.3.2b")
                    current = {"type": "FM", "name": "FM", "tokens": [], "prob": None, "time": None}
                    i += 1
                continue

            current["tokens"].append(tok)
            i += 1

        groups.append(current)
        self.metadata["groups_raw"] = groups

        # Phân tích chi tiết từng nhóm: gió / VIS / mây / thời tiết
        parsed_groups = [self._parse_group_tokens(g) for g in groups]
        self.metadata["groups"] = parsed_groups

        base = parsed_groups[0]
        if base["wind"] is None:
            self._add_error("STAGE1", "Thiếu nhóm gió bề mặt bắt buộc trong nhóm chính (BASE).",
                             ValidationErrorType.ERROR, "1656-IV.2.3",
                             "Thêm nhóm gió dạng dddffGfmfmKT, ví dụ '27003KT'.")
        if base["visibility"] is None:
            self._add_error("STAGE1", "Thiếu nhóm tầm nhìn ngang bắt buộc (VVVV hoặc CAVOK) trong nhóm chính.",
                             ValidationErrorType.ERROR, "1656-IV.2.4",
                             "Thêm nhóm tầm nhìn, ví dụ '9999' hoặc 'CAVOK'.")
        if base["cavok"] is False and not base["clouds"] and not base["vv"]:
            self._add_error(
                "STAGE1", "Thiếu nhóm mây (hoặc tầm nhìn thẳng đứng VVhshshs, hoặc NSC) trong nhóm chính.",
                ValidationErrorType.ERROR, "1656-IV.2.6",
                "Thêm nhóm mây, ví dụ 'FEW015 BKN050' hoặc 'NSC' nếu không có mây nguy hiểm.",
            )

    def _parse_group_tokens(self, g: Dict) -> Dict:
        info = {
            "type": g["type"], "name": g["name"], "prob": g["prob"], "time": g["time"],
            "wind": None, "visibility": None, "cavok": False, "vv": None,
            "clouds": [], "weather": [], "nsw": False, "temp_groups": [], "unknown": [],
        }
        for tok in g["tokens"]:
            if re.match(r"^(VRB|\d{3})\d{2,3}(G\d{2,3})?(KT|MPS)$", tok):
                info["wind"] = self._validate_wind_group(tok, g["name"])
                continue
            if tok == "CAVOK":
                info["cavok"] = True
                info["visibility"] = 9999
                continue
            if re.match(r"^\d{4}$", tok):
                self._validate_vis_group(tok, g["name"])
                info["visibility"] = int(tok)
                continue
            if re.match(r"^VV\d{3}$", tok):
                self._validate_vv_group(tok, g["name"])
                info["vv"] = tok
                continue
            if re.match(r"^(FEW|SCT|BKN|OVC)\d{3}(CB|TCU)?$", tok):
                self._validate_cloud_group(tok, g["name"])
                info["clouds"].append(tok)
                continue
            if tok in ("NSC", "SKC"):
                info["clouds"].append(tok)
                continue
            if tok == "NSW":
                info["nsw"] = True
                continue
            if re.match(r"^(TX|TN)\d{2}/\d{4}Z$", tok):
                info["temp_groups"].append(tok)
                continue
            if WEATHER_RE.match(tok):
                self._validate_weather_group(tok, g["name"])
                info["weather"].append(tok)
                continue
            info["unknown"].append(tok)

        if len(info["weather"]) > 3:
            self._add_error(
                "STAGE1",
                f"Nhóm '{g['name']}' có {len(info['weather'])} hiện tượng thời tiết, vượt quá tối đa 3 hiện tượng cho phép.",
                ValidationErrorType.ERROR, "1656-IV.2.5",
                "Chỉ giữ lại tối đa 3 hiện tượng thời tiết quan trọng nhất trong 1 nhóm.",
            )
        for u in info["unknown"]:
            self._add_warning(
                "STAGE1", f"Nhóm '{g['name']}' chứa mã không nhận diện được: '{u}'.",
                ValidationErrorType.WARNING, "1656-IV.2",
                "Kiểm tra lại chính tả hoặc tham chiếu Chương I/IV để xác định mã đúng.",
            )
        return info

    # -- Validate gió -----------------------------------------------------
    def _validate_wind_group(self, token: str, group_name: str) -> Dict:
        m = re.match(r"^(VRB|\d{3})(\d{2,3})(G(\d{2,3}))?(KT|MPS)$", token)
        direction, speed_str, _, gust_str, unit = m.groups()
        speed = int(speed_str)
        gust = int(gust_str) if gust_str else None

        if unit != "KT":
            self._add_error(
                "STAGE1",
                f"Nhóm gió '{token}': đơn vị '{unit}' không đúng. TAF tại Việt Nam quy định dùng đơn vị 'KT' (knot).",
                ValidationErrorType.ERROR, "1656-I.2.3 (áp dụng chung)",
                "Đổi đơn vị thành KT.",
            )

        if len(speed_str) == 2 and speed >= 100:
            self._add_error(
                "STAGE1", f"Nhóm gió '{token}': tốc độ ≥100kt phải mã hoá dạng P99KT, không dùng 2 chữ số.",
                ValidationErrorType.ERROR, "1656-IV.2.3",
                f"Sửa '{speed_str}' thành 'P99'.",
            )
        if len(speed_str) == 3 and speed_str != "P99":
            self._add_error(
                "STAGE1", f"Nhóm gió '{token}': phần tốc độ 3 chữ số chỉ được dùng dạng 'P99' (≥100kt).",
                ValidationErrorType.ERROR, "1656-IV.2.3",
            )

        if direction != "VRB":
            dir_int = int(direction)
            if not (0 <= dir_int <= 360):
                self._add_error("STAGE1", f"Hướng gió '{direction}' trong '{token}' ngoài phạm vi 000-360°.",
                                 ValidationErrorType.ERROR, "1656-IV.2.3")
            elif dir_int % 10 != 0:
                self._add_warning(
                    "STAGE1", f"Hướng gió '{direction}' trong '{token}' nên làm tròn đến chục độ gần nhất.",
                    ValidationErrorType.WARNING, "1656-IV.2.3",
                )

        if gust is not None:
            if gust <= speed:
                self._add_error(
                    "STAGE1",
                    f"Nhóm gió '{token}': tốc độ gió giật ({gust}kt) phải LỚN HƠN tốc độ trung bình ({speed}kt).",
                    ValidationErrorType.ERROR, "1656-IV.2.3",
                    f"Sửa gió giật thành lớn hơn {speed}kt, ví dụ 'G{speed + 10}'.",
                )
            elif gust - speed < 10:
                self._add_warning(
                    "STAGE1",
                    f"Nhóm gió '{token}': gió giật chỉ nên báo khi vượt tốc độ trung bình ≥10kt "
                    f"(hiện chênh {gust - speed}kt).",
                    ValidationErrorType.WARNING, "1656-IV.2.3",
                    f"Bỏ phần gió giật hoặc tăng lên tối thiểu {speed + 10}kt.",
                )

        return {"raw": token, "dir": direction, "speed": speed, "gust": gust, "group": group_name}

    # -- Validate VIS -------------------------------------------------------
    def _validate_vis_group(self, token: str, group_name: str):
        vis = int(token)
        if vis > 9999:
            self._add_error("STAGE1", f"Tầm nhìn '{token}' vượt quá 9999m.", ValidationErrorType.ERROR,
                             "1656-IV.2.4")
            return
        if vis < 800:
            if vis % 50 != 0:
                self._add_error(
                    "STAGE1", f"Tầm nhìn '{token}'m (<800m) phải theo bước 50m.",
                    ValidationErrorType.ERROR, "1656-IV.2.4",
                    f"Làm tròn xuống bước 50m gần nhất (ví dụ {round(vis / 50) * 50:04d}).",
                )
        elif vis < 5000:
            if vis % 100 != 0:
                self._add_error(
                    "STAGE1", f"Tầm nhìn '{token}'m (800-4999m) phải theo bước 100m.",
                    ValidationErrorType.ERROR, "1656-IV.2.4",
                    f"Làm tròn xuống bước 100m gần nhất (ví dụ {round(vis / 100) * 100:04d}).",
                )
        else:
            if vis != 9999 and vis % 1000 != 0:
                self._add_error(
                    "STAGE1", f"Tầm nhìn '{token}'m (≥5000m) phải theo bước 1000m (hoặc 9999 nếu ≥10km).",
                    ValidationErrorType.ERROR, "1656-IV.2.4",
                    f"Làm tròn xuống bước 1000m gần nhất, hoặc dùng '9999' nếu ≥10km.",
                )

    def _validate_vv_group(self, token: str, group_name: str):
        h = int(token[2:5])
        if not (0 <= h <= 20):
            self._add_warning(
                "STAGE1", f"Tầm nhìn thẳng đứng '{token}' ({h * 100}ft) có vẻ ngoài phạm vi thường gặp (0-2000ft).",
                ValidationErrorType.WARNING, "1656-IV.2.6",
            )

    # -- Validate mây -------------------------------------------------------
    def _validate_cloud_group(self, token: str, group_name: str):
        m = re.match(r"^(FEW|SCT|BKN|OVC)(\d{3})(CB|TCU)?$", token)
        cover, height_str, special = m.groups()
        height = int(height_str)
        if height > 100:
            self._add_warning(
                "STAGE1",
                f"Nhóm mây '{token}': độ cao {height * 100}ft (>10000ft/3000m) thường không cần báo trừ khi là CB/TCU.",
                ValidationErrorType.WARNING, "1656-I.2.7",
            )

    # -- Validate hiện tượng thời tiết --------------------------------------
    def _validate_weather_group(self, token: str, group_name: str):
        m = WEATHER_RE.match(token)
        vc, intensity, descriptor, phenomena = m.groups()

        if vc and intensity:
            self._add_error(
                "STAGE1", f"'{token}': tiếp diễn lân cận 'VC' không đi kèm cường độ (+/-).",
                ValidationErrorType.ERROR, "1656-I.Bảng1-5",
                f"Bỏ dấu {intensity} khi dùng VC (ví dụ 'VC{phenomena}').",
            )
        if intensity == "-" and any(p in ("DS", "SS", "FC") for p in self._split_phenom(phenomena)):
            self._add_error(
                "STAGE1", f"'{token}': không báo cường độ nhẹ (-) cho bão bụi/bão cát/mây hình phễu.",
                ValidationErrorType.ERROR, "1656-I.2.6",
                f"Bỏ dấu '-' (giữ nguyên hoặc dùng '+' nếu là vòi rồng/cột nước mạnh).",
            )
        if descriptor == "FZ" and not any(p in ("RA", "DZ", "FG", "UP") for p in self._split_phenom(phenomena)):
            self._add_warning(
                "STAGE1", f"'{token}': 'FZ' (đông kết) thường chỉ dùng với RA, DZ, FG (hoặc UP cho hệ thống tự động).",
                ValidationErrorType.WARNING, "1656-I.Bảng1-4",
            )

    @staticmethod
    def _split_phenom(phenom_str: str) -> List[str]:
        codes = sorted(ALL_PHENOM, key=len, reverse=True)
        out, s = [], phenom_str
        while s:
            for c in codes:
                if s.startswith(c):
                    out.append(c)
                    s = s[len(c):]
                    break
            else:
                break
        return out

    # ------------------------------------------------------------------
    # STAGE 2: Thời gian (mục 1 Chương IV)
    # ------------------------------------------------------------------
    def _stage2_temporal_validation(self):
        issue_time = self.metadata.get("issue_time", "")
        validity = self.metadata.get("validity_period", "")
        if not issue_time or not validity:
            return

        issue_dd, issue_hh, issue_mm = int(issue_time[0:2]), int(issue_time[2:4]), int(issue_time[4:6])
        start, end = validity.split("/")
        start_dd, start_hh = int(start[0:2]), int(start[2:4])
        end_dd, end_hh = int(end[0:2]), int(end[2:4])

        issue_mins = issue_dd * 1440 + issue_hh * 60 + issue_mm
        start_mins = start_dd * 1440 + start_hh * 60
        end_mins = end_dd * 1440 + end_hh * 60
        # Xử lý vòng qua tháng (đơn giản hoá bằng cộng thêm 31 ngày nếu end/issue < start)
        if start_mins < issue_mins - 20 * 1440:
            start_mins += 31 * 1440
        if end_mins < start_mins:
            end_mins += 31 * 1440

        delta = start_mins - issue_mins  # >0: phát trước hiệu lực; <0: phát sau khi đã bắt đầu hiệu lực

        if delta > 60:
            self._add_warning(
                "STAGE2",
                f"Bản tin phát hành sớm hơn giờ bắt đầu hiệu lực {delta} phút (quy định tối đa 60 phút).",
                ValidationErrorType.WARNING, "1656-IV.1",
                "Phát hành TAF gần hơn với giờ bắt đầu hiệu lực (trong vòng 1 giờ trước).",
            )
        elif delta < -30:
            self._add_error(
                "STAGE2",
                f"Bản tin phát hành trễ {-delta} phút sau giờ bắt đầu hiệu lực (quy định tối đa 30 phút).",
                ValidationErrorType.ERROR, "1656-IV.1",
                "Phát hành TAF không muộn hơn 30 phút sau giờ bắt đầu hiệu lực.",
            )

        duration_h = (end_mins - start_mins) / 60
        self.metadata["duration_hours"] = duration_h
        if duration_h <= 0:
            self._add_error("STAGE2", "Giờ kết thúc hiệu lực phải sau giờ bắt đầu hiệu lực.",
                             ValidationErrorType.ERROR, "1656-IV.2.2")
        elif duration_h > 30:
            self._add_error(
                "STAGE2", f"Thời hạn hiệu lực {duration_h:.0f} giờ vượt quá 30 giờ tối đa cho TAF dài.",
                ValidationErrorType.ERROR, "1656-IV.1",
                "Rút ngắn thời hạn hiệu lực xuống tối đa 30 giờ.",
            )
        elif duration_h < 12:
            self.metadata["is_long_taf"] = False
            self._add_warning(
                "STAGE2",
                f"Thời hạn hiệu lực {duration_h:.0f} giờ là TAF NGẮN (dưới 12 giờ) - chỉ áp dụng cho các "
                f"sân bay không phải cảng hàng không quốc tế theo thỏa thuận khai thác cụ thể.",
                ValidationErrorType.INFO, "1656-IV.1",
            )
        else:
            self.metadata["is_long_taf"] = True

        # Kiểm tra thời điểm của các nhóm biến đổi (TEMPO/BECMG/FM/PROB) có nằm trong hiệu lực
        for grp in self.metadata.get("groups", []):
            if grp["type"] == "BASE":
                continue
            gt = grp.get("time")
            if grp["type"] == "FM" and gt and re.match(r"^\d{6}$", gt):
                dd, hh = int(gt[0:2]), int(gt[2:4])
                g_mins = dd * 1440 + hh * 60 + int(gt[4:6])
                if g_mins < start_mins - 20 * 1440:
                    g_mins += 31 * 1440
                if not (start_mins <= g_mins <= end_mins + 5):
                    self._add_error(
                        "STAGE2",
                        f"Thời điểm '{grp['name']}' nằm ngoài khung hiệu lực của TAF ({validity}).",
                        ValidationErrorType.ERROR, "1656-IV.3.2b",
                    )
            elif gt and re.match(r"^\d{4}/\d{4}$", gt):
                gs, ge = gt.split("/")
                gs_mins = int(gs[0:2]) * 1440 + int(gs[2:4]) * 60
                ge_mins = int(ge[0:2]) * 1440 + int(ge[2:4]) * 60
                if gs_mins < start_mins - 20 * 1440:
                    gs_mins += 31 * 1440
                if ge_mins < gs_mins:
                    ge_mins += 31 * 1440
                if not (start_mins - 5 <= gs_mins and ge_mins <= end_mins + 5):
                    self._add_error(
                        "STAGE2",
                        f"Khung thời gian '{grp['name']}' vượt ra ngoài hiệu lực của TAF ({validity}).",
                        ValidationErrorType.ERROR, "1656-IV.3",
                    )

        # Nhóm nhiệt độ TX/TN phải nằm trong hiệu lực
        for grp in self.metadata.get("groups", []):
            for tg in grp.get("temp_groups", []):
                m = re.match(r"^(TX|TN)(\d{2})/(\d{2})(\d{2})Z$", tg)
                _, val, dd, hh = m.groups()
                t_mins = int(dd) * 1440 + int(hh) * 60
                if t_mins < start_mins - 20 * 1440:
                    t_mins += 31 * 1440
                if not (start_mins <= t_mins <= end_mins):
                    self._add_error(
                        "STAGE2",
                        f"Nhóm nhiệt độ '{tg}' có thời điểm nằm ngoài hiệu lực TAF ({validity}).",
                        ValidationErrorType.ERROR, "1656-IV.2.1",
                    )

    # ------------------------------------------------------------------
    # STAGE 3: Ràng buộc khí tượng (CAVOK, tương quan VIS/thời tiết/mây)
    # ------------------------------------------------------------------
    def _stage3_meteorological_validation(self):
        for grp in self.metadata.get("groups", []):
            name = grp["name"]

            # CAVOK không đi kèm hiện tượng thời tiết / mây CB-TCU / mây thấp
            if grp["cavok"]:
                if grp["weather"]:
                    self._add_error(
                        "STAGE3", f"Nhóm '{name}': CAVOK không được đi kèm hiện tượng thời tiết ({', '.join(grp['weather'])}).",
                        ValidationErrorType.ERROR, "1656-IV.2.4",
                        "Bỏ CAVOK hoặc bỏ các hiện tượng thời tiết đã khai báo.",
                    )
                if any(c.endswith(("CB", "TCU")) for c in grp["clouds"]):
                    self._add_error(
                        "STAGE3", f"Nhóm '{name}': CAVOK không được đi kèm mây CB/TCU.",
                        ValidationErrorType.ERROR, "1656-IV.2.4",
                    )
                if grp["vv"]:
                    self._add_error(
                        "STAGE3", f"Nhóm '{name}': CAVOK không được đi kèm tầm nhìn thẳng đứng.",
                        ValidationErrorType.ERROR, "1656-IV.2.4",
                    )

            # Nhóm chính/BECMG/FM phải có VIS+mây (hoặc CAVOK); TEMPO/PROB có thể chỉ có yếu tố thay đổi
            if grp["type"] in ("BASE",) and not grp["cavok"]:
                if grp["visibility"] is None:
                    pass  # đã báo ở Stage1

            V = grp["visibility"]
            if V is not None and not grp["cavok"]:
                for wx in grp["weather"]:
                    clean = wx.lstrip("+-")
                    has_qualifier = clean[:2] in ("MI", "BC", "PR", "VC")
                    if "FG" in clean and not has_qualifier and V >= 1000:
                        self._add_error(
                            "STAGE3",
                            f"Nhóm '{name}': 'FG' (sương mù dày) chỉ báo khi tầm nhìn <1000m, hiện VIS={V}m.",
                            ValidationErrorType.ERROR, "1656-I.Bảng1-3",
                            "Đổi 'FG' thành 'BR' nếu VIS≥1000m, hoặc giảm VIS xuống dưới 1000m.",
                        )
                    if clean == "BR":
                        if V < 1000:
                            self._add_error(
                                "STAGE3", f"Nhóm '{name}': 'BR' chỉ báo khi 1000m≤VIS<5000m, hiện VIS={V}m (<1000m).",
                                ValidationErrorType.ERROR, "1656-I.2.6",
                                "Đổi 'BR' thành 'FG'.",
                            )
                        elif V > 5000:
                            self._add_error(
                                "STAGE3", f"Nhóm '{name}': 'BR' chỉ báo khi VIS<5000m, hiện VIS={V}m.",
                                ValidationErrorType.ERROR, "1656-I.2.6",
                                "Bỏ 'BR' vì VIS đã vượt 5000m.",
                            )
                    if clean in ("HZ", "FU", "DU", "SA") and V > 5000:
                        self._add_error(
                            "STAGE3",
                            f"Nhóm '{name}': '{clean}' không được báo khi VIS>5000m (hiện VIS={V}m).",
                            ValidationErrorType.ERROR, "1656-I.2.6 (Lưu ý)",
                            f"Bỏ '{clean}' vì VIS đã vượt 5000m.",
                        )

            # CB/TCU nên đi kèm hiện tượng dông (khuyến nghị, không phải lỗi cứng)
            has_cb = any(c.endswith(("CB", "TCU")) for c in grp["clouds"])
            has_ts = any("TS" in w for w in grp["weather"])
            if has_cb and not has_ts and not grp["cavok"]:
                self._add_warning(
                    "STAGE3",
                    f"Nhóm '{name}': có mây CB/TCU nhưng không khai báo hiện tượng dông (TS/TSRA...). "
                    f"Kiểm tra lại nếu đúng là có mây tích dông.",
                    ValidationErrorType.WARNING, "1656-I.2.7",
                )

    # ------------------------------------------------------------------
    # STAGE 4: Nhất quán & ngưỡng biến đổi giữa nhóm chính và BECMG/TEMPO/FM
    # (mục 3.1, 3.2, 3.3 Chương IV)
    # ------------------------------------------------------------------
    def _stage4_consistency_checks(self):
        groups = self.metadata.get("groups", [])
        if not groups:
            return
        base = groups[0]

        # PROB không dùng với BECMG hoặc FM (chỉ dùng với TEMPO hoặc đứng riêng trước value-group)
        for g in groups:
            if g["prob"] is not None and g["type"] not in ("TEMPO", "PROB"):
                self._add_error(
                    "STAGE4",
                    f"Nhóm '{g['name']}': không được dùng PROB{g['prob']} với BECMG hoặc FM.",
                    ValidationErrorType.ERROR, "1656-IV.3.1",
                    f"Bỏ PROB{g['prob']} khỏi nhóm '{g['type']}', hoặc chuyển yếu tố này sang TEMPO.",
                )

        # So khớp thứ tự thời gian của các nhóm biến đổi (không lùi về trước nhóm trước nó)
        last_start = None
        for g in groups[1:]:
            gt = g.get("time")
            start_mins = None
            if g["type"] == "FM" and gt and re.match(r"^\d{6}$", gt):
                start_mins = int(gt[0:2]) * 1440 + int(gt[2:4]) * 60 + int(gt[4:6])
            elif gt and re.match(r"^\d{4}/\d{4}$", gt):
                start_mins = int(gt[0:2]) * 1440 + int(gt[2:4]) * 60
            if start_mins is not None and last_start is not None and start_mins < last_start - 5:
                self._add_warning(
                    "STAGE4",
                    f"Nhóm '{g['name']}' có thời điểm bắt đầu sớm hơn nhóm biến đổi liền trước - kiểm tra lại thứ tự thời gian.",
                    ValidationErrorType.WARNING, "1656-IV.3",
                )
            if start_mins is not None:
                last_start = start_mins

        # Ngưỡng biến đổi cho từng nhóm BECMG/TEMPO/FM/PROB so với nhóm chính (baseline)
        baseline_wind = base["wind"]
        baseline_vis = base["visibility"] if not base["cavok"] else 9999
        for g in groups[1:]:
            if g["type"] == "BASE":
                continue

            # --- Gió ---
            if g["wind"] and baseline_wind:
                bW, gW = baseline_wind, g["wind"]
                dir_change = False
                if bW["dir"] != "VRB" and gW["dir"] != "VRB":
                    diff = abs(int(bW["dir"]) - int(gW["dir"]))
                    diff = min(diff, 360 - diff)
                    if diff >= 60 and (bW["speed"] >= 10 or gW["speed"] >= 10):
                        dir_change = True
                elif bW["dir"] != gW["dir"]:
                    dir_change = True  # đổi sang/khỏi VRB

                speed_change = abs(gW["speed"] - bW["speed"]) >= 10

                gust_change = False
                bG, gG = bW["gust"], gW["gust"]
                if (bG is None) != (gG is None):
                    diff_val = (gG or 0) - bW["speed"] if gG is not None else (bG or 0) - gW["speed"]
                    if abs(diff_val) >= 10 and (bW["speed"] >= 15 or gW["speed"] >= 15):
                        gust_change = True
                elif bG is not None and gG is not None and abs(gG - bG) >= 10 and (bW["speed"] >= 15 or gW["speed"] >= 15):
                    gust_change = True

                if not (dir_change or speed_change or gust_change):
                    self._add_warning(
                        "STAGE4",
                        f"Nhóm '{g['name']}': thay đổi gió ('{bW['raw']}' → '{gW['raw']}') chưa rõ đạt ngưỡng nào "
                        f"trong mục 3.3a Chương IV (hướng đổi ≥60° kèm tốc độ ≥10kt trước/sau; hoặc tốc độ đổi ≥10kt; "
                        f"hoặc gió giật xuất hiện/kết thúc/đổi ≥10kt với tốc độ trung bình ≥15kt).",
                        ValidationErrorType.WARNING, "1656-IV.3.3a",
                        "Kiểm tra lại có cần đưa nhóm gió này vào bản tin biến đổi hay không, "
                        "hoặc bổ sung căn cứ ngưỡng khai thác sân bay áp dụng.",
                    )

            # --- Tầm nhìn ---
            if g["visibility"] is not None and baseline_vis is not None and not g["cavok"]:
                v1, v2 = baseline_vis, g["visibility"]
                crossed = any((v1 < t) != (v2 < t) for t in VIS_CHANGE_THRESHOLDS)
                if not crossed:
                    self._add_warning(
                        "STAGE4",
                        f"Nhóm '{g['name']}': tầm nhìn đổi từ {v1}m sang {v2}m không cắt qua ngưỡng nào "
                        f"trong {VIS_CHANGE_THRESHOLDS} (mục 3.3b Chương IV).",
                        ValidationErrorType.WARNING, "1656-IV.3.3b",
                        "Xem lại có cần đưa tầm nhìn vào nhóm biến đổi này hay không.",
                    )

            # --- Hiện tượng thời tiết ngoài danh mục cho phép trong BECMG/TEMPO/FM ---
            for wx in g["weather"]:
                clean = wx.lstrip("+-")
                is_ts_precip = clean.startswith("TS") and len(clean) > 2
                is_mod_heavy_precip = wx.startswith("+") or (
                    not wx.startswith("-") and any(clean.endswith(p) for p in PRECIP)
                )
                if (
                    clean not in ELIGIBLE_CHANGE_WX_TOKENS
                    and not is_ts_precip
                    and clean != "TS"
                    and not is_mod_heavy_precip
                    and not wx.startswith("-")
                ):
                    # thông tin - không phải lỗi, vì Chương IV vẫn cho phép các hiện tượng khác "khi cần thiết"
                    self._add_warning(
                        "STAGE4",
                        f"Nhóm '{g['name']}': hiện tượng '{wx}' không thuộc nhóm tiêu chí bắt buộc tại mục 3.3c "
                        f"Chương IV; chỉ hợp lệ nếu dự báo viên xét thấy cần thiết cho hoạt động bay.",
                        ValidationErrorType.INFO, "1656-IV.3.3c",
                    )

            # --- Mây: đổi độ cao chân mây thấp nhất BKN/OVC hoặc đổi cấp che phủ dưới 1500ft ---
            base_clouds = [c for c in base["clouds"] if c not in ("NSC", "SKC")]
            curr_clouds = [c for c in g["clouds"] if c not in ("NSC", "SKC")]
            if base_clouds or curr_clouds:
                def lowest_bkn_ovc(cs):
                    heights = [int(c[3:6]) for c in cs if c[:3] in ("BKN", "OVC")]
                    return min(heights) if heights else None

                h1, h2 = lowest_bkn_ovc(base_clouds), lowest_bkn_ovc(curr_clouds)
                cloud_change = False
                if (h1 is None) != (h2 is None):
                    cloud_change = True
                elif h1 is not None and h2 is not None and h1 != h2:
                    if any((h1 < t) != (h2 < t) for t in CLOUD_HEIGHT_THRESHOLDS_FT):
                        cloud_change = True

                def max_cover_below_1500(cs):
                    ranks = {"FEW": 1, "SCT": 2, "BKN": 3, "OVC": 4}
                    vals = [ranks[c[:3]] for c in cs if c[:3] in ranks and int(c[3:6]) < 15]
                    return max(vals) if vals else 0

                c1, c2 = max_cover_below_1500(base_clouds), max_cover_below_1500(curr_clouds)
                if (c1 >= 3) != (c2 >= 3):  # cắt ngưỡng BKN/OVC (>=3) dưới 1500ft
                    cloud_change = True

                if curr_clouds and not cloud_change and g["type"] != "PROB":
                    self._add_warning(
                        "STAGE4",
                        f"Nhóm '{g['name']}': thay đổi mây chưa rõ đạt ngưỡng tại mục 3.3d Chương IV "
                        f"(độ cao chân mây BKN/OVC cắt qua 100/200/500/1000/1500ft, hoặc cấp che phủ đổi "
                        f"qua BKN/OVC ở dưới 1500ft).",
                        ValidationErrorType.WARNING, "1656-IV.3.3d",
                    )

    # ------------------------------------------------------------------
    def _add_error(self, stage, message, error_type, ref=None, suggestion=None):
        self.errors.append(ValidationError(stage=stage, error_type=error_type, message=message,
                                            regulation_ref=ref, suggestion=suggestion))

    def _add_warning(self, stage, message, error_type, ref=None, suggestion=None):
        self.warnings.append(ValidationError(stage=stage, error_type=error_type, message=message,
                                              regulation_ref=ref, suggestion=suggestion))

    def _generate_report(self) -> Dict:
        meta = dict(self.metadata)
        meta.pop("groups_raw", None)  # nội bộ, không cần xuất ra
        return {
            "valid": self.is_valid,
            "errors": [self._error_to_dict(e) for e in self.errors],
            "warnings": [self._error_to_dict(w) for w in self.warnings],
            "metadata": meta,
            "summary": self._summary_text(),
        }

    @staticmethod
    def _error_to_dict(e: ValidationError) -> Dict:
        d = asdict(e)
        d["error_type"] = e.error_type.value
        return d

    def _summary_text(self) -> str:
        n_err = len([e for e in self.errors if e.error_type == ValidationErrorType.ERROR])
        n_fatal = len([e for e in self.errors if e.error_type == ValidationErrorType.FATAL])
        n_warn = len(self.warnings)
        if self.is_valid and n_fatal == 0:
            return f"✅ TAF hợp lệ theo 1656/QĐ-CHK ({n_warn} cảnh báo/gợi ý)."
        return f"❌ TAF không hợp lệ ({n_fatal} lỗi nghiêm trọng, {n_err} lỗi, {n_warn} cảnh báo)."


def quick_validate(taf_string: str) -> Dict:
    """Hàm tiện dụng cho Streamlit / các nơi khác gọi trực tiếp."""
    validator = TAFValidator(taf_string)
    return validator.validate()


if __name__ == "__main__":
    samples = [
        # Ví dụ hợp lệ, lấy tương tự mục 3.2 Chương IV tài liệu 1656
        "TAF VVDN 130500Z 1306/1406 31015KT 8000 -SHRA FEW005 FEW010CB SCT018 BKN050 "
        "BECMG 1310/1312 36004KT 4000 RA SCT010 BKN050=",
        # Ví dụ có PROB + TEMPO
        "TAF VVNB 122300Z 1300/1324 27003KT 2500 BR FEW005 SCT050 "
        "PROB30 1300/1303 0800 FG BECMG 1303/1305 8000 NSW=",
        # Ví dụ lỗi: PROB dùng với BECMG (không hợp lệ), thiếu nhóm gió
        "TAF VVNB 122300Z 1300/1324 2500 BR FEW005 PROB30 BECMG 1303/1305 8000 NSW=",
    ]
    for s in samples:
        print("=" * 80)
        print(s)
        report = quick_validate(s)
        print(report["summary"])
        for e in report["errors"]:
            print("  [ERR]", e["message"])
        for w in report["warnings"]:
            print("  [WARN]", w["message"])
