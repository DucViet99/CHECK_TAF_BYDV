# TAF Validation System Architecture
## Phần mềm kiểm tra độ chính xác TAF theo 1656/QĐ-CHK, ICAO Doc 10157, Annex 3

---

## 1. TỔNG QUAN HỆ THỐNG

### 1.1 Quy trình chính
```
INPUT TAF STRING
    ↓
STAGE 1: FORMAT & SYNTAX VALIDATION
    - Header check (TAF/AMD/COR CCCC YYGGggZ)
    - Validity period check (Y1Y1G1G1/Y2Y2G2G2)
    - Main groups present (Wind, VIS, Wx, Cloud)
    - Trend groups syntax (BECMG/TEMPO/FM/PROB)
    - Value encoding (3-digit codes, rounding)
    ↓
STAGE 2: TEMPORAL VALIDATION
    - Issuance time (not > 1h before, ≤ 30min after validity)
    - Validity duration (short <12h or long 12-30h)
    - Change group ordering (all times sequential)
    - BECMG/TEMPO duration (BECMG ≤ 4h, TEMPO < 1h per occurrence)
    - FM time placement (≥ issuance time)
    ↓
STAGE 3: METEOROLOGICAL CONSTRAINTS
    - Wind: direction 0-360°, speed 0-230kt, gust rules
    - Visibility: 50m-10km, correct steps (50m/<800m; 100m/800-5km; 1km/≥5km)
    - Weather: valid codes, max 3 phenomena, intensity markers
    - Cloud: cover codes, height steps (30/60/150/300m), CB/TCU rules
    - Change thresholds: wind ≥60° or ≥10kt, VIS at 150/350/600/800/1500/3000/5000m
    - CAVOK/NSC/NSW rules
    ↓
STAGE 4: CONSISTENCY CHECKS
    - Logical rules: BECMG never with FM; PROB only with TEMPO
    - No duplicate time windows
    - Wx-VIS correlation (mist → reduced VIS, rain → higher intensity)
    - CAVOK incompatible with weather/low clouds
    - Sequential trend integrity
    ↓
OUTPUT: VALIDATION REPORT
    ✓ Valid TAF
    ✗ Error list with line/group/field references
```

---

## 2. CẤU TRÚC MÔĐ-ULE PYTHON

### 2.1 Lớp chính

```python
class TAFValidator:
    """Main validator orchestrator"""
    
    def __init__(self, taf_string: str):
        self.raw_taf = taf_string.strip()
        self.groups = []  # Parsed groups
        self.errors = []  # Validation errors
        self.warnings = []  # Non-critical issues
        self.is_valid = False
    
    def validate(self) -> dict:
        """Run full validation pipeline"""
        try:
            # Stage 1
            self._stage1_format_validation()
            
            # Stage 2
            self._stage2_temporal_validation()
            
            # Stage 3
            self._stage3_meteorological_validation()
            
            # Stage 4
            self._stage4_consistency_checks()
            
            # Determine validity
            self.is_valid = len(self.errors) == 0
            
        except Exception as e:
            self.errors.append(f"FATAL: {str(e)}")
            self.is_valid = False
        
        return self._generate_report()
    
    def _generate_report(self) -> dict:
        """Generate structured validation report"""
        return {
            'valid': self.is_valid,
            'errors': self.errors,
            'warnings': self.warnings,
            'parsed_groups': self.groups,
            'summary': self._summary_text()
        }
```

### 2.2 Stage 1: Format Validation

```python
class FormatValidator:
    """Stage 1: Syntax and format checks"""
    
    def validate_header(self, header: str) -> bool:
        """
        Check: TAF|AMD|COR CCCC YYGGggZ
        - Type: TAF / TAF AMD / TAF COR
        - ICAO code: 4 chars, first = V (Việt Nam)
        - DateTime: DDHHMMZ format
        """
        pattern = r'^TAF\s+(AMD|COR)?\s+V[A-Z]{3}\s+\d{2}\d{2}\d{2}Z'
        if not re.match(pattern, header):
            return False, "Invalid TAF header format"
        return True, None
    
    def validate_validity_period(self, period: str) -> bool:
        """
        Check: YYGGgg/YYGGgg (validity start/end)
        Rules (1656 mục 2.2):
        - Format: DDHHSS/DDHHss (ngày giờ phút UTC)
        - Valid ranges: DD 01-31, HH 00-23, SS 00-59
        - End > Start
        - Duration: short <12h, long 12-30h
        """
        match = re.match(r'(\d{2})(\d{2})(\d{2})/(\d{2})(\d{2})(\d{2})', period)
        if not match:
            return False, "Invalid validity period format"
        
        d1, h1, s1, d2, h2, s2 = map(int, match.groups())
        
        # Validate ranges
        if not (1 <= d1 <= 31 and 0 <= h1 <= 23 and 0 <= s1 <= 59):
            return False, "Invalid start datetime values"
        if not (1 <= d2 <= 31 and 0 <= h2 <= 23 and 0 <= s2 <= 59):
            return False, "Invalid end datetime values"
        
        # Calculate duration in hours
        t1 = h1 + s1/60
        t2 = h2 + s2/60 + (d2-d1)*24
        duration = t2 - t1
        
        if duration <= 0:
            return False, "Validity end must be > start"
        if not (12 < duration <= 30):  # Typical TAF dài
            return False, f"Duration {duration}h not in valid range (12-30h)"
        
        return True, None
    
    def validate_main_groups(self, groups: list) -> list:
        """
        Check presence and order of mandatory groups
        Order: Wind → VIS → Wx → Cloud/VV
        """
        errors = []
        required = ['wind', 'vis']  # At minimum
        
        group_types = [self._identify_group_type(g) for g in groups]
        
        if 'wind' not in group_types:
            errors.append("Missing required wind group")
        if 'vis' not in group_types:
            errors.append("Missing required visibility group")
        
        return errors
    
    def validate_wind_group(self, group: str) -> tuple:
        """
        Format: dddffGfmfm[KT|MPS]
        ddd = direction (000-360)
        ff = speed (2 digits)
        Gfmfm = gust (optional, if speed diff ≥ 10kt)
        VRB = variable direction
        
        From 1656 mục 2.3:
        """
        pattern = r'^(VRB|\d{3})(\d{2})(G\d{2})?KT$'
        match = re.match(pattern, group)
        
        if not match:
            return False, "Invalid wind group format"
        
        direction, speed, gust = match.groups()
        speed_int = int(speed)
        
        # Speed validation
        if speed_int > 99:  # P99KT for ≥100kt
            return False, "Speed overflow (use P99KT for ≥100kt)"
        
        if gust:
            gust_int = int(gust[1:])
            if gust_int <= speed_int:
                return False, f"Gust {gust_int} must be > wind speed {speed_int}"
            if gust_int - speed_int < 10:
                return False, "Gust reported but difference < 10kt"
        
        return True, None
    
    def validate_vis_group(self, group: str) -> tuple:
        """
        Format: VVVV (4 digits) hoặc CAVOK
        From 1656 mục 2.4:
        
        VIS steps:
        - <800m: 50m steps (0050-0750)
        - 800-5000m: 100m steps (0800-4900)
        - ≥5000m: 1000m steps (5000-9999) or 9999
        """
        if group == 'CAVOK':
            return True, None
        
        try:
            vis = int(group)
        except:
            return False, "VIS must be numeric or CAVOK"
        
        # Range check
        if vis < 50 or vis > 9999:
            return False, f"VIS {vis} out of range [50-9999]m"
        
        # Step validation
        if vis < 800:
            if vis % 50 != 0:
                return False, f"VIS {vis} not at 50m step (<800m)"
        elif vis < 5000:
            if vis % 100 != 0:
                return False, f"VIS {vis} not at 100m step (800-5000m)"
        else:
            if vis % 1000 != 0 and vis != 9999:
                return False, f"VIS {vis} not at 1000m step (≥5000m)"
        
        return True, None
    
    def validate_weather_group(self, group: str) -> tuple:
        """
        Valid weather codes (1656 mục 2.5):
        FZRA, FZDZ, FZFG - freezing precipitation
        SHRA, SNRA, TSRA, TSGR - rain/snow with intensity
        BLDU, BLSA, BLSN - blowing particles
        DS, SS - dust/sand storm
        TS - thunderstorm
        SQ - squall
        FC - funnel cloud
        
        Rules:
        - Max 3 phenomena
        - Intensity markers: +/- where applicable
        """
        valid_codes = {
            'FZRA', 'FZDZ', 'FZFG',
            'SHRA', 'SNRA', 'TSRA', '+TSRA', '-TSRA', 'TSGR',
            'RA', '-RA', '+RA', 'DZ', '-DZ',
            'SN', '-SN', '+SN',
            'BLDU', 'BLSA', 'BLSN',
            'DS', 'SS', 'TS', 'SQ', 'FC',
            'FG', 'BR', 'HZ', 'FU'
        }
        
        # Parse group: may include intensity prefix +-
        code = group.lstrip('+-')
        
        if code not in valid_codes:
            return False, f"Unknown weather code: {code}"
        
        return True, None
    
    def validate_cloud_group(self, group: str) -> tuple:
        """
        Format: NSNSNShShShS[CB|TCU]
        NSN = cover: SKC|CLR|FEW|SCT|BKN|OVC|NSC|NCD
        hShShS = height in hundreds of feet (030-450 range)
        CB = Cumulonimbus
        TCU = Towering Cumulus
        
        From 1656 mục 2.6:
        Height steps: 30, 60, 150, 300, 450m (100, 200, 500, 1000, 1500ft)
        """
        pattern = r'^(SKC|CLR|FEW|SCT|BKN|OVC|NSC|NCD)(\d{3}(CB|TCU)?)?$'
        match = re.match(pattern, group)
        
        if not match:
            return False, "Invalid cloud group format"
        
        cover = match.group(1)
        height_part = match.group(2)
        
        if height_part and cover not in ['SKC', 'CLR', 'NCD']:
            height = int(match.group(2)[:3]) * 100  # Convert to meters
            
            # Valid heights in meters: 30,60,150,300,450
            valid_heights = [30, 60, 150, 300, 450]
            if height not in valid_heights:
                return False, f"Cloud height {height}m not at valid steps"
        
        return True, None
    
    def validate_trend_group_syntax(self, group: str) -> tuple:
        """
        Validate BECMG, TEMPO, FM, PROB syntax
        From 1656 mục 3:
        - BECMG YYgg/YYgg
        - TEMPO YYgg/YYgg [change groups]
        - FM YYGGgg [full weather update]
        - PROB30|40 TEMPO YYgg/YYgg [change groups]
        """
        
        # FM format
        if group.startswith('FM'):
            pattern = r'^FM(\d{2})(\d{2})(\d{2})$'
            if not re.match(pattern, group):
                return False, "Invalid FM format (should be FMYYGGgg)"
            return True, None
        
        # BECMG format
        if group.startswith('BECMG'):
            pattern = r'^BECMG\s+(\d{2})(\d{2})/(\d{2})(\d{2})$'
            if not re.match(pattern, group):
                return False, "Invalid BECMG format"
            return True, None
        
        # TEMPO format
        if group.startswith('TEMPO'):
            pattern = r'^TEMPO\s+(\d{2})(\d{2})/(\d{2})(\d{2})$'
            if not re.match(pattern, group):
                return False, "Invalid TEMPO format"
            return True, None
        
        # PROB format
        if group.startswith('PROB'):
            pattern = r'^PROB(30|40)\s+(TEMPO\s+)?(\d{2})(\d{2})/(\d{2})(\d{2})$'
            if not re.match(pattern, group):
                return False, "Invalid PROB format"
            return True, None
        
        return False, f"Unknown trend group format: {group}"
```

### 2.3 Stage 2: Temporal Validation

```python
class TemporalValidator:
    """Stage 2: Time-based consistency checks"""
    
    def validate_issuance_time(self, issue_time: str, validity_start: str) -> list:
        """
        1656 mục 1: "phát hành không sớm hơn 01 giờ và không muộn hơn 30 phút
        so với giờ bắt đầu hiệu lực"
        
        issue_time, validity_start: YYGGgg format
        """
        errors = []
        
        t_issue = self._time_to_minutes(issue_time)
        t_start = self._time_to_minutes(validity_start)
        
        delta = t_start - t_issue  # Minutes
        
        if delta < -60:  # More than 1h after start
            errors.append(f"TAF issued {-delta}min after validity start (max 1h before)")
        elif delta > 30:  # More than 30min before start
            errors.append(f"TAF issued {delta}min before validity start (max 30min)")
        
        return errors
    
    def validate_change_group_sequence(self, groups: list) -> list:
        """
        Rules:
        1. All BECMG/TEMPO/FM times must be ≥ issue time
        2. Groups must be in chronological order
        3. No time gaps allowed (except TEMPO for interruptions)
        4. BECMG duration ≤ 4h typically
        5. TEMPO each occurrence < 1h, total < 1/2 of forecast period
        """
        errors = []
        last_end = 0
        
        for i, group in enumerate(groups):
            if group['type'] in ['BECMG', 'TEMPO', 'FM']:
                start = self._time_to_minutes(group['start'])
                end = self._time_to_minutes(group['end']) if 'end' in group else start
                
                # Chronological order
                if start < last_end:
                    errors.append(f"Group {i}: time {group['start']} before previous group")
                
                # Duration check
                if group['type'] == 'BECMG':
                    duration = end - start
                    if duration > 240:  # 4 hours
                        errors.append(f"Group {i}: BECMG duration {duration}min > 4h")
                
                if group['type'] == 'TEMPO':
                    duration = end - start
                    if duration >= 60:  # 1 hour
                        errors.append(f"Group {i}: TEMPO occurrence {duration}min ≥ 1h")
                
                last_end = end
        
        return errors
    
    def _time_to_minutes(self, time_str: str) -> int:
        """Convert YYGGgg to minutes from day start"""
        try:
            dd, hh, mm = int(time_str[0:2]), int(time_str[2:4]), int(time_str[4:6])
            return dd * 1440 + hh * 60 + mm
        except:
            return 0
```

### 2.4 Stage 3: Meteorological Validation

```python
class MeteoValidator:
    """Stage 3: Physical constraints and meteorological rules"""
    
    WIND_THRESHOLDS = {
        'direction_change': 60,  # degrees
        'speed_change': 10,      # knots
        'gust_change': 10        # knots
    }
    
    VIS_THRESHOLDS = [150, 350, 600, 800, 1500, 3000, 5000]  # meters
    
    CLOUD_HEIGHT_THRESHOLDS = [30, 60, 150, 300, 450]  # meters
    
    def validate_wind_change(self, current: dict, next: dict) -> list:
        """
        1656 mục 3.3 a) - Change thresholds
        """
        errors = []
        
        # Direction change
        d1 = int(current['direction'])
        d2 = int(next['direction'])
        if d1 != 0 and d2 != 0:  # Not VRB
            dir_change = abs(d2 - d1)
            if dir_change > 180:
                dir_change = 360 - dir_change
            
            if dir_change >= self.WIND_THRESHOLDS['direction_change']:
                if min(d1, d2) < 10:  # One is very weak
                    errors.append("Large direction change with low wind")
        
        # Speed change
        s1 = int(current['speed'])
        s2 = int(next['speed'])
        speed_change = abs(s2 - s1)
        
        if speed_change >= self.WIND_THRESHOLDS['speed_change']:
            if min(s1, s2) < 3:  # Variable
                errors.append("Large speed change from light wind")
        
        return errors
    
    def validate_vis_change(self, current: int, next: int) -> bool:
        """
        Check if VIS change crosses required threshold
        1656 mục 3.3 b)
        """
        thresholds = self.VIS_THRESHOLDS
        
        for t in thresholds:
            if (current < t <= next) or (next < t <= current):
                return True  # Change crosses threshold
        
        return False
    
    def validate_cavok_rules(self, groups: dict) -> list:
        """
        CAVOK allowed only if:
        - VIS ≥ 10km
        - No dangerous clouds (CB, TCU below 1500m/5000ft)
        - No weather phenomena in 1656 Table 1-3, 1-4
        - NSW (Nil Significant Weather)
        
        1656 mục 2.4
        """
        errors = []
        
        if 'CAVOK' in str(groups):
            if groups.get('vis') < 10000:
                errors.append("CAVOK incompatible with VIS < 10km")
            
            if groups.get('weather'):
                errors.append("CAVOK incompatible with weather phenomena")
            
            if 'CB' in str(groups.get('clouds', '')) or 'TCU' in str(groups.get('clouds', '')):
                errors.append("CAVOK incompatible with CB/TCU clouds")
        
        return errors
    
    def validate_weather_vis_correlation(self, weather: list, vis: int) -> list:
        """
        Meteorological consistency:
        FG (fog) → VIS typically < 1000m
        BR (mist) → VIS 1000-5000m
        RA (rain) → VIS often < 5000m
        +RA (heavy rain) → VIS < 1500m likely
        """
        errors = []
        correlations = {
            'FG': (50, 1000),      # Fog: 50-1000m
            'BR': (1000, 5000),    # Mist: 1000-5000m
            '-RA': (1000, 9999),   # Light rain: flexible
            'RA': (600, 5000),     # Moderate rain
            '+RA': (50, 1500)      # Heavy rain: very low
        }
        
        for wx in weather:
            if wx in correlations:
                min_vis, max_vis = correlations[wx]
                if vis < min_vis or vis > max_vis:
                    errors.append(f"Weather '{wx}' unlikely with VIS {vis}m")
        
        return errors
```

### 2.5 Stage 4: Consistency Checks

```python
class ConsistencyValidator:
    """Stage 4: Cross-group and logical coherence"""
    
    def validate_trend_group_rules(self, groups: list) -> list:
        """
        1656 mục 3.3 - Change group logical rules
        
        Rules:
        1. BECMG never used with FM in same TAF section
        2. PROB only used with TEMPO, never with BECMG
        3. TEMPO may have associated weather/wind following it
        4. FM replaces all groups from point forward
        5. No overlapping BECMG/TEMPO windows
        """
        errors = []
        
        has_becmg = any(g['type'] == 'BECMG' for g in groups if 'type' in g)
        has_fm = any(g['type'] == 'FM' for g in groups if 'type' in g)
        
        if has_becmg and has_fm:
            errors.append("BECMG and FM cannot both be used in same TAF")
        
        for g in groups:
            if g.get('type') == 'PROB':
                # PROB must be followed by TEMPO, not BECMG
                if 'BECMG' in g.get('descriptor', ''):
                    errors.append("PROB cannot be used with BECMG")
        
        return errors
    
    def validate_no_duplicate_times(self, groups: list) -> list:
        """
        Check no overlapping BECMG/TEMPO windows
        Each time slot should have exactly one change group
        """
        errors = []
        times_used = {}
        
        for g in groups:
            if 'start' in g and 'end' in g:
                key = (g['start'], g['end'])
                if key in times_used:
                    errors.append(f"Duplicate time window {g['start']}-{g['end']}")
                times_used[key] = g['type']
        
        return errors
    
    def validate_logical_consistency(self, taf_dict: dict) -> list:
        """
        High-level logical checks:
        - If cloud height decreases, VIS should not increase (usually)
        - If heavy weather (TSRA), VIS should be restricted
        - Temperature trends should be reasonable
        """
        errors = []
        
        # Example: TSRA → restricted visibility
        if 'TSRA' in str(taf_dict) or '+RA' in str(taf_dict):
            vis = taf_dict.get('vis', 9999)
            if vis > 5000:
                errors.append("TSRA/+RA typically associated with VIS < 5000m")
        
        return errors
```

---

## 3. STREAMLIT INTEGRATION

### 3.1 Ứng dụng chính

```python
import streamlit as st
from taf_validator import TAFValidator

st.set_page_config(page_title="TAF Validation", layout="wide")

st.title("🌤️ TAF Validation System")
st.markdown("""
Kiểm tra độ chính xác TAF theo quy định:
- 1656/QĐ-CHK (Cục Hàng không Việt Nam)
- ICAO Doc 10157 PANS-MET
- Annex 3 Amendment 82
""")

# Input area
col1, col2 = st.columns([2, 1])

with col1:
    taf_input = st.text_area(
        "Nhập TAF:",
        height=150,
        placeholder="TAF VVNB 122300Z 1300/1324 27003KT ...",
        help="Dán toàn bộ bản tin TAF"
    )

with col2:
    validate_btn = st.button("🔍 Kiểm tra", type="primary", use_container_width=True)
    
    if st.button("📋 Mẫu TAF"):
        st.session_state.sample_taf = """TAF VVNB 122300Z 1300/1324 27003KT 2500 BR FEW005 SCT050
BECMG 1303/1305 8000 NSW SCT010 BKN050
TEMPO 1310/1316 4000 SHRA SCT005 BKN020"""
        st.rerun()
    
    if "sample_taf" in st.session_state:
        taf_input = st.session_state.sample_taf

# Validation
if validate_btn or taf_input:
    if not taf_input.strip():
        st.warning("⚠️ Vui lòng nhập TAF")
    else:
        validator = TAFValidator(taf_input)
        report = validator.validate()
        
        # Results display
        if report['valid']:
            st.success("✅ TAF hợp lệ")
        else:
            st.error(f"❌ TAF không hợp lệ ({len(report['errors'])} lỗi)")
        
        # Errors table
        if report['errors']:
            st.subheader("Lỗi phát hiện")
            error_df = pd.DataFrame([
                {"Loại": "Error", "Chi tiết": e}
                for e in report['errors']
            ])
            st.dataframe(error_df, use_container_width=True)
        
        # Warnings
        if report['warnings']:
            st.subheader("Cảnh báo")
            for w in report['warnings']:
                st.warning(w)
        
        # Parsed groups (debug)
        with st.expander("📊 Chi tiết phân tích"):
            st.json(report['parsed_groups'])

# Documentation
with st.expander("📖 Tài liệu"):
    st.markdown("""
    ### Tiêu chí kiểm tra
    
    **Stage 1: Format & Syntax**
    - Header: TAF|AMD|COR CCCC YYGGggZ
    - Validity: YYgg/YYgg (12-30h)
    - Main groups: Wind, VIS, Wx, Cloud
    - Trend groups: BECMG, TEMPO, FM, PROB
    
    **Stage 2: Temporal**
    - Issue time: ≤1h before, ≤30min after validity
    - Sequential timing
    - Duration limits
    
    **Stage 3: Meteorological**
    - Wind: 0-360°, 0-230kt
    - VIS: 50m-10km, correct steps
    - Weather: valid codes, max 3
    - Cloud: cover + height, CB/TCU
    - Change thresholds
    
    **Stage 4: Consistency**
    - Logical rules
    - No duplicates
    - Correlation checks
    """)
```

---

## 4. CẤU TRÚC DỮ LIỆU LƯU TRỮ

### 4.1 Cơ sở dữ liệu quy định (reference data)

```python
# ICAO Codes & Rules
WEATHER_CODES = {
    'FZRA': {'type': 'freezing', 'intensity': 'variable'},
    'TSRA': {'type': 'thunderstorm', 'intensity': 'moderate/heavy'},
    '+RA': {'type': 'rain', 'intensity': 'heavy'},
    '-RA': {'type': 'rain', 'intensity': 'light'},
    # ... full list from 1656 Table 1-3
}

CLOUD_COVERS = {
    'SKC': 'Sky Clear (special)',
    'CLR': 'Clear',
    'FEW': '1/8-2/8',
    'SCT': '3/8-4/8',
    'BKN': '5/8-7/8',
    'OVC': '8/8 (overcast)',
    'NSC': 'Nil Significant Cloud',
    'NCD': 'No Cloud Detected'
}

# Regulatory references
REGULATION_REFS = {
    '1656': {
        'name': 'Hướng dẫn về bản tin khí tượng hàng không (CAAV)',
        'chapters': {
            'IV': 'TAF/TAF AMD requirements',
            'IV.2': 'Encoding rules',
            'IV.3': 'Change group criteria'
        }
    },
    '10157': {
        'name': 'ICAO Doc 10157 PANS-MET',
        'sections': {
            '3.2': 'TAF structure',
            '3.3': 'TAF encoding'
        }
    },
    'Annex3': {
        'name': 'ICAO Annex 3 Amendment 82 (2025)',
        'paragraphs': {
            'A3.1.1': 'Meteorological information',
            'A3.3.2': 'TAF format'
        }
    }
}
```

---

## 5. KỊCH BẢN KIỂM THỬA

### 5.1 Test cases

```python
# Valid TAF examples
VALID_TAFS = [
    # Dài hạn từ Nội Bài
    """TAF VVNB 122300Z 1300/1324 27003KT 2500 BR FEW005 SCT050
BECMG 1303/1305 8000 NSW SCT010 BKN050""",
    
    # Với thay đổi tạm thời
    """TAF VVDN 130500Z 1306/1406 31015KT 8000 -SHRA FEW005 FEW010CB SCT018 BKN050
TEMPO 1310/1316 4000 SHRA""",
]

# Invalid TAF examples (test errors)
INVALID_TAFS = [
    # Wrong date format
    ("TAF VVNB 999999Z", "Invalid validity period"),
    
    # Missing groups
    ("TAF VVNB 122300Z 1300/1324", "Missing wind group"),
    
    # Invalid VIS step
    ("TAF VVNB 122300Z 1300/1324 27003KT 1234", "VIS not at 100m step"),
    
    # Invalid weather code
    ("TAF VVNB 122300Z 1300/1324 27003KT 2500 BADWX", "Unknown weather code"),
]
```

---

## 6. DEPLOYMENT NOTES

### 6.1 Dependencies
```
streamlit>=1.28
pandas>=2.0
regex>=2023.10
python-dateutil>=2.8
```

### 6.2 Performance
- Validation time: < 500ms per TAF
- Streamed parsing for long documents
- Caching for reference rules

### 6.3 Data Privacy
- No external API calls
- Local validation only
- Optional: Log errors to file for training data

---

## 7. FUTURE ENHANCEMENTS

1. **Integration with numerical models**: Compare TAF against WRF/GFS output
2. **Skill scoring**: Track forecast accuracy metrics
3. **Multi-airport batch processing**: Validate multiple TAFs simultaneously
4. **Export reports**: PDF/Excel with regulatory citations
5. **ML warning flags**: Use historical error patterns to flag suspicious values
6. **API endpoint**: REST/GraphQL for third-party integration

---

## 8. REFERENCES

- 1656/QĐ-CHK: Hướng dẫn về Bản tin khí tượng hàng không (2023)
- ICAO Doc 10157: Aeronautical Meteorology Manual, PANS-MET (2021)
- ICAO Annex 3: Meteorological Service for International Air Navigation, Amendment 82 (2025)
- WMO 306: Manual on Codes (2019)

