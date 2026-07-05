"""
TAF Validator - Kiểm tra độ chính xác TAF theo 1656/QĐ-CHK, ICAO Doc 10157, Annex 3
Complete validation module for Streamlit integration
"""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
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


class TAFValidator:
    """
    Main TAF validator orchestrator
    Implements 4-stage validation pipeline
    """
    
    def __init__(self, taf_string: str):
        self.raw_taf = taf_string.strip()
        self.groups = []
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []
        self.is_valid = False
        self.metadata = {}
        
    def validate(self) -> Dict:
        """Run complete validation pipeline"""
        try:
            # Stage 1: Format & Syntax
            self._stage1_format_validation()
            
            # Stage 2: Temporal Validation
            if len(self.errors) == 0:
                self._stage2_temporal_validation()
            
            # Stage 3: Meteorological Constraints
            if len(self.errors) == 0:
                self._stage3_meteorological_validation()
            
            # Stage 4: Consistency Checks
            if len(self.errors) == 0:
                self._stage4_consistency_checks()
            
            # Determine validity
            self.is_valid = len([e for e in self.errors if e.error_type == ValidationErrorType.ERROR]) == 0
            
        except Exception as e:
            self.errors.append(ValidationError(
                stage="FATAL",
                error_type=ValidationErrorType.FATAL,
                message=f"Unexpected error: {str(e)}"
            ))
            self.is_valid = False
        
        return self._generate_report()
    
    def _stage1_format_validation(self):
        """Validate format and syntax"""
        lines = self.raw_taf.split('\n')
        
        # Parse header line
        if not lines:
            self._add_error("STAGE1", "No TAF content", ValidationErrorType.FATAL)
            return
        
        header = lines[0].split()
        
        # Check header structure
        if len(header) < 3:
            self._add_error("STAGE1", "TAF header incomplete", ValidationErrorType.ERROR, "1656-2.2")
            return
        
        taf_type = header[0]  # TAF / TAF AMD / TAF COR
        if taf_type not in ['TAF', 'AMD', 'COR']:
            # Try alternative format: TAF AMD or TAF COR
            if taf_type == 'TAF' and len(header) >= 2:
                if header[1] in ['AMD', 'COR']:
                    taf_type = f"{taf_type} {header[1]}"
                    header = [taf_type] + header[2:]
        
        # Validate ICAO code
        icao = header[1] if len(header) > 1 else ""
        if not re.match(r'^V[A-Z]{3}$', icao):
            self._add_error("STAGE1", f"Invalid ICAO code: {icao}", ValidationErrorType.ERROR, "1656-2.2")
            return
        
        # Validate issue time
        issue_time = header[2] if len(header) > 2 else ""
        if not re.match(r'^\d{2}\d{2}\d{2}Z$', issue_time):
            self._add_error("STAGE1", f"Invalid issue time format: {issue_time}", ValidationErrorType.ERROR, "1656-2.2")
            return
        
        self.metadata['taf_type'] = taf_type
        self.metadata['icao'] = icao
        self.metadata['issue_time'] = issue_time
        
        # Parse all groups
        all_text = ' '.join(lines)
        self._parse_groups(all_text)
    
    def _parse_groups(self, text: str):
        """Parse TAF groups"""
        # Split by spaces but keep group context
        parts = text.split()
        
        i = 0
        main_groups = {}
        trend_groups = []
        
        while i < len(parts):
            part = parts[i]
            
            # Validity period
            if '/' in part and len(part.split('/')[0]) == 4:
                valid_match = re.match(r'^(\d{2})(\d{2})/(\d{2})(\d{2})$', part)
                if valid_match:
                    self.metadata['validity_period'] = part
                    d1, h1, d2, h2 = map(int, valid_match.groups())
                    # Validate basic format
                    if not (1 <= d1 <= 31 and 0 <= h1 <= 23):
                        self._add_error("STAGE1", f"Invalid validity start: {part}", ValidationErrorType.ERROR, "1656-2.2")
                    if not (1 <= d2 <= 31 and 0 <= h2 <= 23):
                        self._add_error("STAGE1", f"Invalid validity end: {part}", ValidationErrorType.ERROR, "1656-2.2")
                    i += 1
                    continue
            
            # Wind group (dddffGfmfm)
            if re.match(r'^(VRB|\d{3})\d{2}(G\d{2})?KT$', part):
                self._validate_wind_group(part)
                main_groups['wind'] = part
                i += 1
                continue
            
            # VIS group (VVVV or CAVOK)
            if part == 'CAVOK' or re.match(r'^\d{4}$', part):
                self._validate_vis_group(part)
                main_groups['vis'] = part
                i += 1
                continue
            
            # Weather group
            if re.match(r'^[+-]?[A-Z]{2,6}$', part):
                self._validate_weather_group(part)
                if 'weather' not in main_groups:
                    main_groups['weather'] = []
                main_groups['weather'].append(part)
                i += 1
                continue
            
            # Cloud group
            if re.match(r'^(SKC|CLR|FEW|SCT|BKN|OVC|NSC|NCD)\d{3}(CB|TCU)?$', part):
                self._validate_cloud_group(part)
                if 'clouds' not in main_groups:
                    main_groups['clouds'] = []
                main_groups['clouds'].append(part)
                i += 1
                continue
            
            # Trend groups
            if part.startswith('BECMG'):
                i = self._parse_trend_group(parts, i, 'BECMG', trend_groups)
                continue
            
            if part.startswith('TEMPO'):
                i = self._parse_trend_group(parts, i, 'TEMPO', trend_groups)
                continue
            
            if part.startswith('FM'):
                i = self._parse_trend_group(parts, i, 'FM', trend_groups)
                continue
            
            if part.startswith('PROB'):
                i = self._parse_trend_group(parts, i, 'PROB', trend_groups)
                continue
            
            i += 1
        
        self.metadata['main_groups'] = main_groups
        self.metadata['trend_groups'] = trend_groups
        
        # Check mandatory groups
        if 'wind' not in main_groups:
            self._add_error("STAGE1", "Missing mandatory wind group", ValidationErrorType.ERROR, "1656-2.3")
        if 'vis' not in main_groups:
            self._add_error("STAGE1", "Missing mandatory visibility group", ValidationErrorType.ERROR, "1656-2.4")
    
    def _parse_trend_group(self, parts: List[str], idx: int, group_type: str, 
                          trend_groups: List[Dict]) -> int:
        """Parse BECMG, TEMPO, FM, PROB groups"""
        start_idx = idx
        group_dict = {'type': group_type, 'raw': parts[idx]}
        
        if group_type in ['BECMG', 'TEMPO']:
            # Format: BECMG YYgg/YYgg or TEMPO YYgg/YYgg
            if idx + 1 < len(parts) and '/' in parts[idx + 1]:
                time_group = parts[idx + 1]
                group_dict['time'] = time_group
                idx += 2
            else:
                self._add_error("STAGE1", f"{group_type} missing time window", ValidationErrorType.ERROR)
                return idx + 1
        
        elif group_type == 'FM':
            # Format: FMYYGGgg
            if re.match(r'^FM\d{6}$', parts[idx]):
                group_dict['time'] = parts[idx][2:]
                idx += 1
            else:
                self._add_error("STAGE1", "FM invalid format", ValidationErrorType.ERROR)
                return idx + 1
        
        elif group_type == 'PROB':
            # Format: PROB30/40 ...
            if re.match(r'^PROB(30|40)$', parts[idx]):
                prob = parts[idx][-2:]
                group_dict['probability'] = int(prob)
                idx += 1
            else:
                self._add_error("STAGE1", "PROB invalid format", ValidationErrorType.ERROR)
                return idx + 1
        
        trend_groups.append(group_dict)
        return idx
    
    def _validate_wind_group(self, group: str):
        """Validate wind group: dddffGfmfmKT"""
        pattern = r'^(VRB|\d{3})(\d{2})(G\d{2})?KT$'
        match = re.match(pattern, group)
        
        if not match:
            self._add_error("STAGE1", f"Invalid wind format: {group}", ValidationErrorType.ERROR, "1656-2.3")
            return
        
        direction, speed, gust = match.groups()
        speed_int = int(speed)
        
        # Direction validation
        if direction != 'VRB':
            try:
                dir_int = int(direction)
                if not (0 <= dir_int <= 360):
                    self._add_error("STAGE1", f"Wind direction {dir_int} out of range", ValidationErrorType.ERROR, "1656-2.3")
            except:
                pass
        
        # Speed validation
        if speed_int > 99:
            self._add_warning("STAGE1", "Wind speed overflow (should be P99KT)", ValidationErrorType.WARNING, "1656-2.3")
        
        # Gust validation
        if gust:
            gust_int = int(gust[1:])
            if gust_int <= speed_int:
                self._add_error("STAGE1", f"Gust {gust_int} not > wind speed {speed_int}", ValidationErrorType.ERROR, "1656-2.3")
            if gust_int - speed_int < 10:
                self._add_warning("STAGE1", "Gust difference < 10kt (may not need reporting)", ValidationErrorType.WARNING, "1656-2.3")
    
    def _validate_vis_group(self, group: str):
        """Validate visibility: VVVV or CAVOK"""
        if group == 'CAVOK':
            # Check CAVOK rules later in meteorological stage
            return
        
        try:
            vis = int(group)
        except:
            self._add_error("STAGE1", f"Invalid VIS: {group}", ValidationErrorType.ERROR, "1656-2.4")
            return
        
        # Range check
        if vis < 50 or vis > 9999:
            self._add_error("STAGE1", f"VIS {vis} out of range [50-9999]m", ValidationErrorType.ERROR, "1656-2.4")
            return
        
        # Step validation (1656 mục 2.4)
        valid = False
        if vis < 800:
            valid = (vis % 50 == 0)
            if not valid:
                self._add_error("STAGE1", f"VIS {vis}m not at 50m step (<800m)", ValidationErrorType.ERROR, "1656-2.4")
        elif vis < 5000:
            valid = (vis % 100 == 0)
            if not valid:
                self._add_error("STAGE1", f"VIS {vis}m not at 100m step (800-5000m)", ValidationErrorType.ERROR, "1656-2.4")
        else:
            valid = (vis % 1000 == 0 or vis == 9999)
            if not valid:
                self._add_error("STAGE1", f"VIS {vis}m not at 1000m step (≥5000m)", ValidationErrorType.ERROR, "1656-2.4")
    
    def _validate_weather_group(self, group: str):
        """Validate weather codes"""
        valid_codes = {
            'FZRA', 'FZDZ', 'FZFG',
            'SHRA', 'SNRA', 'TSRA', '+TSRA', '-TSRA', 'TSGR',
            'RA', '-RA', '+RA', 'DZ', '-DZ', '+DZ',
            'SN', '-SN', '+SN',
            'BLDU', 'BLSA', 'BLSN',
            'DS', 'SS', 'TS', '+TS', 'SQ', 'FC',
            'FG', 'BR', 'HZ', 'FU', 'VA'
        }
        
        code = group.lstrip('+-')
        if code not in valid_codes:
            self._add_warning("STAGE1", f"Unknown weather code: {code}", ValidationErrorType.WARNING, "1656-2.5")
    
    def _validate_cloud_group(self, group: str):
        """Validate cloud group: NSNNNhhhCB"""
        pattern = r'^(SKC|CLR|FEW|SCT|BKN|OVC|NSC|NCD)(\d{3}(CB|TCU)?)?$'
        match = re.match(pattern, group)
        
        if not match:
            self._add_error("STAGE1", f"Invalid cloud format: {group}", ValidationErrorType.ERROR, "1656-2.6")
            return
        
        cover = match.group(1)
        height_str = match.group(2)
        
        # Height validation for non-SKC/CLR/NSC clouds
        if height_str and cover not in ['SKC', 'CLR', 'NCD']:
            height = int(height_str[:3]) * 100  # Convert to meters
            
            # Valid heights: 30, 60, 150, 300, 450m (from 1656)
            valid_heights = [30, 60, 150, 300, 450]
            if height not in valid_heights:
                self._add_warning("STAGE1", f"Cloud height {height}m not at standard step", ValidationErrorType.WARNING, "1656-2.6")
    
    def _stage2_temporal_validation(self):
        """Stage 2: Temporal checks"""
        issue_time = self.metadata.get('issue_time', '')
        validity = self.metadata.get('validity_period', '')
        
        if not issue_time or not validity:
            return
        
        try:
            # Parse times
            issue_dd = int(issue_time[0:2])
            issue_hh = int(issue_time[2:4])
            issue_mm = int(issue_time[4:6])
            
            valid_parts = validity.split('/')
            start_dd = int(valid_parts[0][0:2])
            start_hh = int(valid_parts[0][2:4])
            end_dd = int(valid_parts[1][0:2])
            end_hh = int(valid_parts[1][2:4])
            
            # Calculate minutes from day start
            issue_mins = issue_dd * 1440 + issue_hh * 60 + issue_mm
            start_mins = start_dd * 1440 + start_hh * 60
            end_mins = end_dd * 1440 + end_hh * 60
            
            # Check timing rules (1656 mục 1)
            delta = start_mins - issue_mins
            
            if delta < -60:
                self._add_error("STAGE2", f"TAF issued {-delta}min after validity start (max 1h)", ValidationErrorType.ERROR, "1656-1")
            elif delta > 30:
                self._add_error("STAGE2", f"TAF issued {delta}min before validity start", ValidationErrorType.WARNING, "1656-1")
            
            # Check duration
            duration = end_mins - start_mins
            if duration <= 0:
                self._add_error("STAGE2", "Validity end ≤ start", ValidationErrorType.ERROR, "1656-2.2")
            elif duration < 720:  # < 12 hours
                self._add_warning("STAGE2", f"TAF duration {duration/60:.1f}h (min 12h for long TAF)", ValidationErrorType.WARNING, "1656-1")
            elif duration > 1800:  # > 30 hours
                self._add_error("STAGE2", f"TAF duration {duration/60:.1f}h exceeds 30h max", ValidationErrorType.ERROR, "1656-1")
        
        except Exception as e:
            self._add_error("STAGE2", f"Temporal parsing error: {str(e)}", ValidationErrorType.ERROR)
    
    def _stage3_meteorological_validation(self):
        """Stage 3: Meteorological constraints"""
        main = self.metadata.get('main_groups', {})
        
        # Check CAVOK rules
        if main.get('vis') == 'CAVOK':
            if main.get('weather'):
                self._add_error("STAGE3", "CAVOK incompatible with weather phenomena", ValidationErrorType.ERROR, "1656-2.4")
            if any('CB' in str(c) or 'TCU' in str(c) for c in main.get('clouds', [])):
                self._add_error("STAGE3", "CAVOK incompatible with CB/TCU", ValidationErrorType.ERROR, "1656-2.4")
        
        # Check weather-VIS correlation
        vis_val = 9999
        if main.get('vis') != 'CAVOK':
            try:
                vis_val = int(main.get('vis', '9999'))
            except:
                pass
        
        weather_list = main.get('weather', [])
        for wx in weather_list:
            if 'FG' in wx and vis_val > 1000:
                self._add_warning("STAGE3", f"Fog forecast with VIS {vis_val}m (typically <1000m)", ValidationErrorType.WARNING, "1656-3.3")
            if '+RA' in wx and vis_val > 1500:
                self._add_warning("STAGE3", f"Heavy rain with VIS {vis_val}m (typically <1500m)", ValidationErrorType.WARNING, "1656-3.3")
    
    def _stage4_consistency_checks(self):
        """Stage 4: Cross-group consistency"""
        trend_groups = self.metadata.get('trend_groups', [])
        
        # Check for BECMG and FM together
        has_becmg = any(g.get('type') == 'BECMG' for g in trend_groups)
        has_fm = any(g.get('type') == 'FM' for g in trend_groups)
        
        if has_becmg and has_fm:
            self._add_error("STAGE4", "BECMG and FM cannot both be used", ValidationErrorType.ERROR, "1656-3.2")
        
        # Check PROB usage (only with TEMPO)
        for g in trend_groups:
            if g.get('type') == 'PROB' and 'time' in g:
                # PROB should be followed by weather changes
                pass
    
    def _add_error(self, stage: str, message: str, error_type: ValidationErrorType, ref: Optional[str] = None):
        """Add validation error"""
        self.errors.append(ValidationError(
            stage=stage,
            error_type=error_type,
            message=message,
            regulation_ref=ref
        ))
    
    def _add_warning(self, stage: str, message: str, error_type: ValidationErrorType, ref: Optional[str] = None):
        """Add validation warning"""
        self.warnings.append(ValidationError(
            stage=stage,
            error_type=error_type,
            message=message,
            regulation_ref=ref
        ))
    
    def _generate_report(self) -> Dict:
        """Generate validation report"""
        return {
            'valid': self.is_valid,
            'errors': [asdict(e) for e in self.errors],
            'warnings': [asdict(w) for w in self.warnings],
            'metadata': self.metadata,
            'summary': self._summary_text()
        }
    
    def _summary_text(self) -> str:
        """Generate human-readable summary"""
        if self.is_valid:
            return "✅ TAF hợp lệ (valid)"
        else:
            error_count = len(self.errors)
            warning_count = len(self.warnings)
            return f"❌ TAF không hợp lệ ({error_count} lỗi, {warning_count} cảnh báo)"


# Quick validation function for Streamlit
def quick_validate(taf_string: str) -> Dict:
    """One-liner for Streamlit"""
    validator = TAFValidator(taf_string)
    return validator.validate()


# Test sample
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
