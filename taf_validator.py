"""
TAF Validator - Kiểm tra độ chính xác TAF theo 1656/QĐ-CHK, ICAO Doc 10157, Annex 3
Complete validation module for Streamlit integration

CHANGELOG (bản sửa):
- Sửa parser: tách đúng header khỏi phần thân, không còn nuốt nhầm "TAF"/ICAO
  làm nhóm thời tiết.
- Sửa lỗi mỗi nhóm TEMPO/BECMG chỉ lấy được thời gian mà không gán đúng
  VIS/WX/CLOUD của riêng nó -> giờ mỗi trend group có 'fields' riêng.
- Hỗ trợ tổ hợp PROB30/PROB40 + TEMPO (PROB40 TEMPO ...).
- Sửa quy đổi độ cao mây: hshshs là hàng TRĂM FEET (không phải mét); bỏ bảng
  "valid_heights" sai đơn vị gây cảnh báo giả.
- Bỏ rule giới hạn thời lượng TEMPO (không có giới hạn cứng theo Annex 3 -
  TEMPO chỉ quy định dao động từng lần <1h và tổng <1/2 chu kỳ, không giới
  hạn độ dài cửa sổ thời gian ghi trong nhóm).
- Thêm rule kiểm tra thời lượng BECMG: nên ≤2h (cảnh báo nếu 2-4h, lỗi nếu >4h),
  đúng với định nghĩa "gradual change... usually two hours".
- Nới ngưỡng thời lượng hiệu lực tối thiểu của TAF xuống 6h (thay vì 12h) vì
  TAF ngắn 9h (VVDB, VVTX...) là hợp lệ theo thông lệ khu vực APAC.
- Nới ngưỡng "issued quá sớm" (issued before start) vì thông lệ phổ biến là
  phát trước ~1h so với giờ bắt đầu hiệu lực.
"""

import re
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class ValidationErrorType(Enum):
    """Error severity levels"""
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class ValidationError:
    """Structure for validation errors"""
    stage: str
    error_type: ValidationErrorType
    group: Optional[str] = None
    message: str = ""
    regulation_ref: Optional[str] = None


WIND_RE = re.compile(r'^(VRB|\d{3})(\d{2})(G(\d{2,3}))?KT$')
VIS_RE = re.compile(r'^\d{4}$')
TIME_WINDOW_RE = re.compile(r'^(\d{2})(\d{2})/(\d{2})(\d{2})$')
CLOUD_RE = re.compile(r'^(SKC|CLR|FEW|SCT|BKN|OVC|NSC|NCD)(\d{3}(CB|TCU)?)?$')
WEATHER_RE = re.compile(r'^[+-]?(VC)?[A-Z]{2,6}$')
FM_RE = re.compile(r'^FM(\d{6})$')
PROB_RE = re.compile(r'^PROB(30|40)$')

# Tokens that are NOT weather phenomena even though they match the generic
# weather regex shape - this was the root cause of "Unknown weather code: TAF"
# style false positives.
NON_WEATHER_TOKENS = {
    'NSC', 'NCD', 'SKC', 'CLR', 'NSW', 'CAVOK',
    'BECMG', 'TEMPO', 'PROB30', 'PROB40', 'AMD', 'COR', 'TAF',
}

VALID_WEATHER_CODES = {
    'FZRA', 'FZDZ', 'FZFG',
    'SHRA', 'SHSN', 'SHGR', 'SHGS',
    'TSRA', 'TSGR', 'TSGS', 'TS',
    'RA', 'DZ', 'SN', 'SG', 'PL', 'GR', 'GS', 'IC',
    'BLDU', 'BLSA', 'BLSN', 'DRDU', 'DRSA', 'DRSN',
    'DS', 'SS', 'SQ', 'FC',
    'FG', 'BR', 'HZ', 'FU', 'VA', 'DU', 'SA', 'PY',
    'MIFG', 'BCFG', 'PRFG',
    'NSW',
}


class TAFValidator:
    """
    Main TAF validator orchestrator
    Implements 4-stage validation pipeline
    """

    def __init__(self, taf_string: str):
        self.raw_taf = taf_string.strip()
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []
        self.is_valid = False
        self.metadata = {}

    def validate(self) -> Dict:
        """Run complete validation pipeline"""
        try:
            self._stage1_format_validation()

            if len([e for e in self.errors if e.error_type == ValidationErrorType.FATAL]) == 0:
                self._stage2_temporal_validation()
                self._stage3_meteorological_validation()
                self._stage4_consistency_checks()

            self.is_valid = len([e for e in self.errors if e.error_type in
                                  (ValidationErrorType.ERROR, ValidationErrorType.FATAL)]) == 0

        except Exception as e:
            self.errors.append(ValidationError(
                stage="FATAL",
                error_type=ValidationErrorType.FATAL,
                message=f"Unexpected error: {str(e)}"
            ))
            self.is_valid = False

        return self._generate_report()

    # ------------------------------------------------------------------ #
    # STAGE 1 : format & syntax
    # ------------------------------------------------------------------ #
    def _stage1_format_validation(self):
        """Validate header format and tokenize the body separately."""
        text = self.raw_taf.replace('=', ' ')
        tokens = text.split()

        if not tokens:
            self._add_error("STAGE1", "No TAF content", ValidationErrorType.FATAL)
            return

        idx = 0
        taf_type = "TAF"

        if tokens[idx] == 'TAF':
            idx += 1
        else:
            self._add_error("STAGE1", "Bản tin thiếu từ khóa 'TAF' ở đầu",
                             ValidationErrorType.ERROR, "1656-2.2")
            # Vẫn tiếp tục xử lý phần còn lại như thể có TAF, để không chặn
            # toàn bộ các kiểm tra phía sau.

        if idx < len(tokens) and tokens[idx] in ('AMD', 'COR'):
            taf_type = f"TAF {tokens[idx]}"
            idx += 1

        icao = tokens[idx] if idx < len(tokens) else ""
        if not re.match(r'^V[A-Z]{3}$', icao):
            self._add_error("STAGE1", f"Invalid ICAO code: {icao}", ValidationErrorType.ERROR, "1656-2.2")
            return
        idx += 1

        issue_time = tokens[idx] if idx < len(tokens) else ""
        if not re.match(r'^\d{6}Z$', issue_time):
            self._add_error("STAGE1", f"Invalid issue time format: {issue_time}", ValidationErrorType.ERROR, "1656-2.2")
            return
        idx += 1

        validity = tokens[idx] if idx < len(tokens) else ""
        m = TIME_WINDOW_RE.match(validity)
        if not m:
            self._add_error("STAGE1", f"Invalid/missing validity period: {validity}", ValidationErrorType.ERROR, "1656-2.2")
            return
        d1, h1, d2, h2 = map(int, m.groups())
        if not (1 <= d1 <= 31 and 0 <= h1 <= 24):
            self._add_error("STAGE1", f"Invalid validity start: {validity}", ValidationErrorType.ERROR, "1656-2.2")
        if not (1 <= d2 <= 31 and 0 <= h2 <= 24):
            self._add_error("STAGE1", f"Invalid validity end: {validity}", ValidationErrorType.ERROR, "1656-2.2")
        idx += 1

        self.metadata['taf_type'] = taf_type
        self.metadata['icao'] = icao
        self.metadata['issue_time'] = issue_time
        self.metadata['validity_period'] = validity

        # Only the tokens AFTER the header are the body - this is the key fix:
        # previously the whole raw text (including "TAF", ICAO, issue time)
        # was re-scanned, causing those tokens to be misread as weather groups.
        body_tokens = tokens[idx:]
        self._parse_groups(body_tokens)

    def _parse_groups(self, tokens: List[str]):
        """Parse the main (prevailing) group of the TAF body."""
        i = 0
        n = len(tokens)
        main_groups = {}
        trend_groups = []

        while i < n:
            part = tokens[i]

            # Change-group keywords are checked FIRST - previously they were
            # checked last, so e.g. the literal string "TEMPO" (5 letters)
            # matched the generic weather-code regex before ever reaching the
            # dedicated TEMPO branch.
            if part == 'BECMG':
                i = self._parse_trend_group(tokens, i, 'BECMG', trend_groups)
                continue
            if part == 'TEMPO':
                i = self._parse_trend_group(tokens, i, 'TEMPO', trend_groups)
                continue
            if FM_RE.match(part):
                i = self._parse_trend_group(tokens, i, 'FM', trend_groups)
                continue
            if PROB_RE.match(part):
                i = self._parse_trend_group(tokens, i, 'PROB', trend_groups)
                continue

            if WIND_RE.match(part):
                self._validate_wind_group(part)
                main_groups['wind'] = part
                i += 1
                continue

            if part == 'CAVOK' or VIS_RE.match(part):
                self._validate_vis_group(part)
                main_groups['vis'] = part
                i += 1
                continue

            if CLOUD_RE.match(part):
                self._validate_cloud_group(part)
                main_groups.setdefault('clouds', []).append(part)
                i += 1
                continue

            if part not in NON_WEATHER_TOKENS and WEATHER_RE.match(part):
                self._validate_weather_group(part)
                main_groups.setdefault('weather', []).append(part)
                i += 1
                continue

            # Unrecognized token (e.g. TX/TN temperature groups, QNH, wind
            # shear WS...) - skip without forcing a false weather match.
            i += 1

        self.metadata['main_groups'] = main_groups
        self.metadata['trend_groups'] = trend_groups

        if 'wind' not in main_groups:
            self._add_error("STAGE1", "Missing mandatory wind group", ValidationErrorType.ERROR, "1656-2.3")
        if 'vis' not in main_groups:
            self._add_error("STAGE1", "Missing mandatory visibility group", ValidationErrorType.ERROR, "1656-2.4")

    def _parse_trend_group(self, tokens: List[str], idx: int, group_type: str,
                            trend_groups: List[Dict]) -> int:
        """Parse BECMG / TEMPO / FM / PROB and everything that belongs to it,
        up to (but not including) the next change-group keyword."""
        group_dict = {'type': group_type, 'raw': tokens[idx]}
        i = idx + 1

        if group_type in ('BECMG', 'TEMPO'):
            if i < len(tokens) and TIME_WINDOW_RE.match(tokens[i]):
                group_dict['time'] = tokens[i]
                i += 1
            else:
                self._add_error("STAGE1", f"{group_type} missing/invalid time window",
                                 ValidationErrorType.ERROR, "1656-3.2")

        elif group_type == 'FM':
            m = FM_RE.match(tokens[idx])
            if m:
                group_dict['time'] = m.group(1)  # DDHHMM
            else:
                self._add_error("STAGE1", "FM invalid format", ValidationErrorType.ERROR, "1656-3.2")

        elif group_type == 'PROB':
            m = PROB_RE.match(tokens[idx])
            probability = int(m.group(1)) if m else None
            group_dict['probability'] = probability

            # PROB30/40 may stand alone with its own time window, or be
            # immediately followed by TEMPO (e.g. "PROB40 TEMPO 0513/0516 ...").
            if i < len(tokens) and tokens[i] == 'TEMPO':
                nested_end = self._parse_trend_group(tokens, i, 'TEMPO', trend_groups)
                nested = trend_groups.pop()  # the TEMPO we just parsed
                group_dict.update(nested)
                group_dict['type'] = 'PROB_TEMPO'
                group_dict['probability'] = probability
                trend_groups.append(group_dict)
                return nested_end
            elif i < len(tokens) and TIME_WINDOW_RE.match(tokens[i]):
                group_dict['time'] = tokens[i]
                i += 1
            else:
                self._add_error("STAGE1", "PROB missing time window (or TEMPO)",
                                 ValidationErrorType.ERROR, "1656-3.2")

        # Consume the fields (wind/vis/weather/cloud) that belong to this
        # change group, stopping at the next change-group keyword.
        fields = {}
        while i < len(tokens):
            t = tokens[i]
            if t in ('BECMG', 'TEMPO') or FM_RE.match(t) or PROB_RE.match(t):
                break
            if WIND_RE.match(t):
                self._validate_wind_group(t)
                fields['wind'] = t
            elif t == 'CAVOK' or VIS_RE.match(t):
                self._validate_vis_group(t)
                fields['vis'] = t
            elif CLOUD_RE.match(t):
                self._validate_cloud_group(t)
                fields.setdefault('clouds', []).append(t)
            elif t not in NON_WEATHER_TOKENS and WEATHER_RE.match(t):
                self._validate_weather_group(t)
                fields.setdefault('weather', []).append(t)
            elif t == 'NSW':
                fields.setdefault('weather', []).append('NSW')
            i += 1

        group_dict['fields'] = fields
        trend_groups.append(group_dict)
        return i

    def _validate_wind_group(self, group: str):
        """Validate wind group: dddffGfmfmKT"""
        match = WIND_RE.match(group)
        if not match:
            self._add_error("STAGE1", f"Invalid wind format: {group}", ValidationErrorType.ERROR, "1656-2.3")
            return

        direction, speed, _, gust = match.groups()
        speed_int = int(speed)

        if direction != 'VRB':
            dir_int = int(direction)
            if not (0 <= dir_int <= 360):
                self._add_error("STAGE1", f"Wind direction {dir_int} out of range", ValidationErrorType.ERROR, "1656-2.3")

        if gust:
            gust_int = int(gust)
            if gust_int <= speed_int:
                self._add_error("STAGE1", f"Gust {gust_int} not > wind speed {speed_int}", ValidationErrorType.ERROR, "1656-2.3")
            elif gust_int - speed_int < 10:
                self._add_warning("STAGE1", "Gust difference < 10kt (may not need reporting)", ValidationErrorType.WARNING, "1656-2.3")

    def _validate_vis_group(self, group: str):
        """Validate visibility: VVVV or CAVOK"""
        if group == 'CAVOK':
            return

        vis = int(group)

        if vis > 9999:
            self._add_error("STAGE1", f"VIS {vis} out of range [0000-9999]m", ValidationErrorType.ERROR, "1656-2.4")
            return

        if vis < 800:
            if vis % 50 != 0:
                self._add_error("STAGE1", f"VIS {vis}m not at 50m step (<800m)", ValidationErrorType.ERROR, "1656-2.4")
        elif vis < 5000:
            if vis % 100 != 0:
                self._add_error("STAGE1", f"VIS {vis}m not at 100m step (800-5000m)", ValidationErrorType.ERROR, "1656-2.4")
        else:
            if not (vis % 1000 == 0 or vis == 9999):
                self._add_error("STAGE1", f"VIS {vis}m not at 1000m step (>=5000m)", ValidationErrorType.ERROR, "1656-2.4")

    def _validate_weather_group(self, group: str):
        """Validate weather codes"""
        code = group.lstrip('+-')
        if code not in VALID_WEATHER_CODES:
            self._add_warning("STAGE1", f"Unknown weather code: {group}", ValidationErrorType.WARNING, "1656-2.5")

    def _validate_cloud_group(self, group: str):
        """Validate cloud group: NsNsNshshshs[CB|TCU]
        hshshs is in HUNDREDS OF FEET (not meters) - this was a unit bug in
        the previous version that produced false "non-standard height"
        warnings on every single cloud group.
        """
        match = CLOUD_RE.match(group)
        if not match:
            self._add_error("STAGE1", f"Invalid cloud format: {group}", ValidationErrorType.ERROR, "1656-2.6")
            return
        # No further "snapping" validation here: reporting increments for
        # cloud base height vary by altitude band and are not a fixed list,
        # so we only check the 3-digit hundreds-of-feet syntax (already
        # enforced by CLOUD_RE) to avoid false positives.

    # ------------------------------------------------------------------ #
    # STAGE 2 : temporal
    # ------------------------------------------------------------------ #
    def _stage2_temporal_validation(self):
        issue_time = self.metadata.get('issue_time', '')
        validity = self.metadata.get('validity_period', '')

        if not issue_time or not validity:
            return

        try:
            issue_dd = int(issue_time[0:2])
            issue_hh = int(issue_time[2:4])
            issue_mm = int(issue_time[4:6])

            m = TIME_WINDOW_RE.match(validity)
            start_dd, start_hh, end_dd, end_hh = map(int, m.groups())

            issue_mins = issue_dd * 1440 + issue_hh * 60 + issue_mm
            start_mins = start_dd * 1440 + start_hh * 60
            end_mins = end_dd * 1440 + end_hh * 60

            delta = start_mins - issue_mins  # >0: issued before start

            if delta < -60:
                self._add_error("STAGE2", f"TAF issued {-delta} phút SAU khi hiệu lực đã bắt đầu (tối đa cho phép 60 phút)",
                                 ValidationErrorType.ERROR, "1656-1")
            elif delta > 90:
                self._add_warning("STAGE2", f"TAF phát {delta} phút trước giờ bắt đầu hiệu lực (thông lệ ~60 phút)",
                                   ValidationErrorType.WARNING, "1656-1")

            duration = end_mins - start_mins
            if duration <= 0:
                self._add_error("STAGE2", "Validity end <= start", ValidationErrorType.ERROR, "1656-2.2")
            elif duration < 360:  # < 6h : dưới mức tối thiểu theo quy định vùng APAC
                self._add_error("STAGE2", f"TAF duration {duration/60:.1f}h thấp hơn tối thiểu 6h", ValidationErrorType.ERROR, "1656-1")
            elif duration > 1800:  # > 30h
                self._add_error("STAGE2", f"TAF duration {duration/60:.1f}h exceeds 30h max", ValidationErrorType.ERROR, "1656-1")

            self._validate_trend_group_times(start_mins, end_mins)

        except Exception as e:
            self._add_error("STAGE2", f"Temporal parsing error: {str(e)}", ValidationErrorType.ERROR)

    def _validate_trend_group_times(self, taf_start_mins: int, taf_end_mins: int):
        """Cross-check BECMG/TEMPO/PROB time windows against the overall
        validity period, and apply the BECMG <=2h guideline (not TEMPO -
        TEMPO has no fixed maximum window length)."""
        trend_groups = self.metadata.get('trend_groups', [])

        def to_mins(dd, hh):
            # hh may be 24 (end-of-day notation)
            return dd * 1440 + hh * 60

        prev_end = None
        for g in trend_groups:
            time_str = g.get('time')
            if not time_str or '/' not in time_str:
                continue
            m = TIME_WINDOW_RE.match(time_str)
            if not m:
                continue
            d1, h1, d2, h2 = map(int, m.groups())
            g_start = to_mins(d1, h1)
            g_end = to_mins(d2, h2)
            label = g.get('raw', g.get('type'))

            if g_start < taf_start_mins or g_end > taf_end_mins:
                self._add_error(
                    "STAGE2",
                    f"{label} {time_str}: nằm ngoài hiệu lực TAF chính",
                    ValidationErrorType.ERROR, "1656-3.2"
                )

            if g.get('type') == 'BECMG':
                dur_h = (g_end - g_start) / 60
                if dur_h > 4:
                    self._add_error(
                        "STAGE2",
                        f"BECMG {time_str} kéo dài {dur_h:.1f}h - BECMG là chuyển đổi dần, không nên vượt quá 4h",
                        ValidationErrorType.ERROR, "1656-3.2"
                    )
                elif dur_h > 2:
                    self._add_warning(
                        "STAGE2",
                        f"BECMG {time_str} dài {dur_h:.1f}h (thông lệ BECMG thường <=2h)",
                        ValidationErrorType.WARNING, "1656-3.2"
                    )
            # TEMPO: không áp đặt giới hạn độ dài cửa sổ thời gian - chỉ quy
            # định các dao động bên trong nó thường <1h/lần và tổng <1/2 chu
            # kỳ, đây là điều nội dung khí tượng chứ không phải cú pháp có
            # thể kiểm chứng tự động từ độ dài group.

    # ------------------------------------------------------------------ #
    # STAGE 3 : meteorological constraints
    # ------------------------------------------------------------------ #
    def _stage3_meteorological_validation(self):
        main = self.metadata.get('main_groups', {})

        if main.get('vis') == 'CAVOK':
            if main.get('weather'):
                self._add_error("STAGE3", "CAVOK incompatible with weather phenomena", ValidationErrorType.ERROR, "1656-2.4")
            if any('CB' in str(c) or 'TCU' in str(c) for c in main.get('clouds', [])):
                self._add_error("STAGE3", "CAVOK incompatible with CB/TCU", ValidationErrorType.ERROR, "1656-2.4")

        vis_val = 9999
        if main.get('vis') not in (None, 'CAVOK'):
            try:
                vis_val = int(main.get('vis'))
            except (TypeError, ValueError):
                pass

        for wx in main.get('weather', []):
            if 'FG' in wx and vis_val > 1000:
                self._add_warning("STAGE3", f"Fog forecast with VIS {vis_val}m (typically <1000m)", ValidationErrorType.WARNING, "1656-3.3")
            if '+RA' in wx and vis_val > 1500:
                self._add_warning("STAGE3", f"Heavy rain with VIS {vis_val}m (typically <1500m)", ValidationErrorType.WARNING, "1656-3.3")

    # ------------------------------------------------------------------ #
    # STAGE 4 : cross-group consistency
    # ------------------------------------------------------------------ #
    def _stage4_consistency_checks(self):
        trend_groups = self.metadata.get('trend_groups', [])

        has_becmg = any(g.get('type') == 'BECMG' for g in trend_groups)
        has_fm = any(g.get('type') == 'FM' for g in trend_groups)

        if has_becmg and has_fm:
            self._add_error("STAGE4", "BECMG and FM cannot both be used", ValidationErrorType.ERROR, "1656-3.2")

        # Change groups (BECMG/FM) must be in chronological order and must
        # not overlap with each other (TEMPO/PROB_TEMPO are allowed to
        # overlap the prevailing timeline by definition, so they're excluded
        # from this specific check).
        ordered = [g for g in trend_groups if g.get('type') in ('BECMG', 'FM') and g.get('time')]
        # (kept intentionally simple; a full chronology check would need the
        # FM's implicit end = next FM/BECMG start, which is beyond this pass)

    def _add_error(self, stage: str, message: str, error_type: ValidationErrorType, ref: Optional[str] = None):
        self.errors.append(ValidationError(stage=stage, error_type=error_type, message=message, regulation_ref=ref))

    def _add_warning(self, stage: str, message: str, error_type: ValidationErrorType, ref: Optional[str] = None):
        self.warnings.append(ValidationError(stage=stage, error_type=error_type, message=message, regulation_ref=ref))

    def _generate_report(self) -> Dict:
        return {
            'valid': self.is_valid,
            'errors': [asdict(e) for e in self.errors],
            'warnings': [asdict(w) for w in self.warnings],
            'metadata': self.metadata,
            'summary': self._summary_text()
        }

    def _summary_text(self) -> str:
        if self.is_valid:
            return "✅ TAF hợp lệ (valid)"
        error_count = len(self.errors)
        warning_count = len(self.warnings)
        return f"❌ TAF không hợp lệ ({error_count} lỗi, {warning_count} cảnh báo)"


def quick_validate(taf_string: str) -> Dict:
    """One-liner for Streamlit"""
    validator = TAFValidator(taf_string)
    return validator.validate()


if __name__ == "__main__":
    sample = """TAF VVNB 122300Z 1300/1324 27003KT 2500 BR FEW005 SCT050
BECMG 1303/1305 8000 NSW SCT010 BKN050"""

    report = quick_validate(sample)
    print(f"Valid: {report['valid']}")
    print(f"Summary: {report['summary']}")
    if report['errors']:
        print("Errors:")
        for e in report['errors']:
            print(f"  - {e}")
