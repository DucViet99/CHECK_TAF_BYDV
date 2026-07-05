"""
TAF Validation App - Streamlit Frontend
Kiểm tra độ chính xác TAF theo 1656/QĐ-CHK, ICAO Doc 10157, Annex 3 Amendment 82
"""

import streamlit as st
import pandas as pd
import json
from taf_validator import quick_validate, ValidationErrorType
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="TAF Validation System",
    page_icon="🌤️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] button {
        font-size: 16px;
    }
    .error-box {
        background-color: #ffebee;
        border-left: 4px solid #f44336;
        padding: 12px;
        margin: 8px 0;
        border-radius: 4px;
    }
    .warning-box {
        background-color: #fff3e0;
        border-left: 4px solid #ff9800;
        padding: 12px;
        margin: 8px 0;
        border-radius: 4px;
    }
    .success-box {
        background-color: #e8f5e9;
        border-left: 4px solid #4caf50;
        padding: 12px;
        margin: 8px 0;
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.title("🌤️ TAF Validation System")
st.markdown("""
**Kiểm tra tự động độ chính xác bản tin TAF (Aerodrome Forecast)**
- ✅ Kiểm soát cú pháp và định dạng
- ✅ Xác thực thời gian (issuance, validity, change groups)
- ✅ Ràng buộc khí tượng (wind, VIS, weather, cloud)
- ✅ Kiểm tra tính nhất quán (consistency rules)

**Quy định tham chiếu:**
- 1656/QĐ-CHK (Cục Hàng không Việt Nam)
- ICAO Doc 10157 PANS-MET
- Annex 3 Amendment 82 (2025)
""")

# Sidebar
with st.sidebar:
    st.header("⚙️ Cấu hình")
    
    validation_mode = st.radio(
        "Chế độ xác thực",
        ["Mặc định (all stages)", "Chỉ format", "Format + thời gian"],
        help="Chọn mức độ kiểm tra chi tiết"
    )
    
    show_advanced = st.checkbox("🔬 Chế độ nâng cao (Debug)", value=False)
    
    with st.expander("📋 Tài liệu nhanh"):
        st.markdown("""
        ### TAF Structure
        ```
        TAF CCCC YYGGggZ YYgg/YYgg
        dddffGfmfmKT VVVV w'w' NsNshshshs
        BECMG YYgg/YYgg [changes]
        TEMPO YYgg/YYgg [temporary changes]
        FM YYGGgg [full update]
        ```
        
        ### Common Codes
        - **Wind**: ddd=direction, ff=speed (kt)
        - **VIS**: VVVV (meters) or CAVOK
        - **Weather**: RA(rain), TS(thunderstorm), FG(fog), BR(mist)
        - **Cloud**: FEW/SCT/BKN/OVC + height in hundreds of ft
        
        ### Rules
        - Issue time: ≤1h before, ≤30min after validity
        - Duration: 12-30 hours
        - VIS steps: 50m (<800m), 100m (800-5km), 1km (≥5km)
        - Change threshold: wind ±60° or ±10kt, VIS at certain levels
        """)

# Main content area
tab1, tab2, tab3 = st.tabs(["✏️ Kiểm tra", "📚 Ví dụ", "📖 Hướng dẫn"])

with tab1:
    col1, col2 = st.columns([3, 1])
    
    with col1:
        taf_input = st.text_area(
            "Nhập TAF:",
            height=150,
            placeholder="""TAF VVNB 122300Z 1300/1324 27003KT 2500 BR FEW005 SCT050
BECMG 1303/1305 8000 NSW SCT010 BKN050
TEMPO 1310/1316 4000 SHRA SCT005 BKN020""",
            help="Dán toàn bộ bản tin TAF (ghi chú: từng dòng một nhóm)"
        )
    
    with col2:
        st.write("")
        st.write("")
        validate_btn = st.button("🔍 Kiểm tra", type="primary", use_container_width=True, key="validate_main")
        
        if st.button("📋 Làm mới", use_container_width=True):
            st.rerun()
    
    st.divider()
    
    # Validation execution
    if validate_btn or taf_input:
        if not taf_input.strip():
            st.warning("⚠️ Vui lòng nhập TAF")
        else:
            # Run validation
            with st.spinner("Kiểm tra TAF..."):
                report = quick_validate(taf_input)
            
            # Display result summary
            col_result, col_stats = st.columns([2, 1])
            
            with col_result:
                if report['valid']:
                    st.success("✅ **TAF hợp lệ**")
                else:
                    st.error(f"❌ **TAF không hợp lệ**")

                meta = report.get('metadata', {})
                airport = meta.get('airport')
                if airport:
                    icao = meta.get('icao', '')
                    st.caption(
                        f"🛫 Sân bay: **{airport.get('name', '?')}** ({icao}) — {airport.get('location', '?')} · "
                        f"Loại bản tin: {meta.get('taf_type', 'TAF')} · "
                        f"Hiệu lực: {meta.get('validity_period', '?')} "
                        f"({meta.get('duration_hours', '?')} giờ)"
                    )
            
            with col_stats:
                error_count = len([e for e in report['errors'] if e.get('error_type') in ('ERROR', 'FATAL')])
                warning_count = len(report['warnings'])
                st.metric("Lỗi", error_count, delta=None)
                st.metric("Cảnh báo", warning_count, delta=None)
            
            st.divider()
            
            # Errors and Warnings
            if report['errors']:
                st.subheader("🔴 Lỗi phát hiện")
                for error in report['errors']:
                    stage = error.get('stage', 'UNKNOWN')
                    msg = error.get('message', '')
                    ref = error.get('regulation_ref', '')
                    suggestion = error.get('suggestion', '')
                    
                    ref_str = f" ({ref})" if ref else ""
                    suggestion_str = f"<br/>💡 <em>Gợi ý: {suggestion}</em>" if suggestion else ""
                    st.markdown(f"""
<div class="error-box">
    <strong>[{stage}]</strong> {msg}{ref_str}{suggestion_str}
</div>
""", unsafe_allow_html=True)
            
            if report['warnings']:
                st.subheader("🟡 Cảnh báo / Gợi ý")
                for warning in report['warnings']:
                    stage = warning.get('stage', 'UNKNOWN')
                    msg = warning.get('message', '')
                    ref = warning.get('regulation_ref', '')
                    suggestion = warning.get('suggestion', '')
                    
                    ref_str = f" ({ref})" if ref else ""
                    suggestion_str = f"<br/>💡 <em>Gợi ý: {suggestion}</em>" if suggestion else ""
                    st.markdown(f"""
<div class="warning-box">
    <strong>[{stage}]</strong> {msg}{ref_str}{suggestion_str}
</div>
""", unsafe_allow_html=True)

            if report['valid'] and not report['errors'] and not report['warnings']:
                st.markdown("""
<div class="success-box">
    Không phát hiện lỗi hoặc cảnh báo nào. Bản tin tuân thủ cấu trúc và các ngưỡng quy định tại 1656/QĐ-CHK.
</div>
""", unsafe_allow_html=True)
            
            # Advanced debugging
            if show_advanced and report.get('metadata'):
                with st.expander("🔬 Chi tiết phân tích (Debug)"):
                    st.json({
                        'metadata': report['metadata'],
                        'errors': report['errors'],
                        'warnings': report['warnings']
                    })
            
            # Export option
            col_exp1, col_exp2, col_exp3 = st.columns(3)
            with col_exp1:
                if st.button("📥 Tải JSON", use_container_width=True):
                    st.download_button(
                        label="📥 JSON",
                        data=json.dumps(report, indent=2, ensure_ascii=False),
                        file_name=f"taf_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json"
                    )
            
            with col_exp2:
                if st.button("📊 Tải CSV", use_container_width=True):
                    # Create CSV from errors/warnings
                    records = []
                    for e in report['errors']:
                        records.append({
                            'Stage': e.get('stage'),
                            'Type': 'ERROR',
                            'Message': e.get('message'),
                            'Reference': e.get('regulation_ref', '')
                        })
                    for w in report['warnings']:
                        records.append({
                            'Stage': w.get('stage'),
                            'Type': 'WARNING',
                            'Message': w.get('message'),
                            'Reference': w.get('regulation_ref', '')
                        })
                    
                    if records:
                        df = pd.DataFrame(records)
                        csv = df.to_csv(index=False, encoding='utf-8-sig')
                        st.download_button(
                            label="📊 CSV",
                            data=csv,
                            file_name=f"taf_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )

with tab2:
    st.header("📚 TAF Examples")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("✅ Valid TAF Examples")
        
        examples_valid = {
            "Nội Bài (VVNB) - Standard": """TAF VVNB 122300Z 1300/1324 27003KT 2500 BR FEW005 SCT050
BECMG 1303/1305 8000 NSW SCT010 BKN050""",
            
            "Đà Nẵng (VVDN) - With thunderstorms": """TAF VVDN 130500Z 1306/1406 31015KT 8000 -SHRA FEW005 FEW010CB SCT018 BKN050
TEMPO 1310/1316 4000 SHRA""",
            
            "CAVOK example": """TAF VVTB 150000Z 1500/1618 31005KT CAVOK BKN020 
FM160200 31010KT 9999 SCT015 BKN025""",
        }
        
        selected_example = st.selectbox(
            "Chọn ví dụ hợp lệ:",
            list(examples_valid.keys())
        )
        
        if selected_example:
            example_text = examples_valid[selected_example]
            st.code(example_text, language="plaintext")
            
            if st.button("✅ Kiểm tra ví dụ này", key="valid_example"):
                st.session_state.taf_input = example_text
                st.rerun()
    
    with col2:
        st.subheader("❌ Invalid TAF Examples")
        
        examples_invalid = {
            "Missing wind group": """TAF VVNB 122300Z 1300/1324 2500 BR FEW005 SCT050""",
            
            "Invalid VIS step": """TAF VVNB 122300Z 1300/1324 27003KT 2345 BR FEW005""",
            
            "Unknown weather code": """TAF VVNB 122300Z 1300/1324 27003KT 2500 BADWX FEW005""",
            
            "BECMG + FM together": """TAF VVNB 122300Z 1300/1324 27003KT 2500 BR FEW005
BECMG 1303/1305 8000 NSW
FM130600 31010KT 9999""",
        }
        
        selected_invalid = st.selectbox(
            "Chọn ví dụ lỗi:",
            list(examples_invalid.keys())
        )
        
        if selected_invalid:
            invalid_text = examples_invalid[selected_invalid]
            st.code(invalid_text, language="plaintext")
            
            if st.button("❌ Kiểm tra ví dụ này", key="invalid_example"):
                st.session_state.taf_input = invalid_text
                st.rerun()

with tab3:
    st.header("📖 Hướng dẫn chi tiết")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("TAF Structure (Cấu trúc)")
        st.markdown("""
        ```
        TAF [AMD|COR] CCCC YYGGggZ YYgg/YYgg
         ↑     ↑      ↑     ↑         ↑
         |     |      |     |         └─ Validity: start/end
         |     |      |     └─ Issue time (UTC)
         |     |      └─ Aerodrome ICAO code
         |     └─ Amendment or Correction (optional)
         └─ TAF indicator
        
        [Main groups - all ≥6h forecast]
        dddffGfmfmKT    ← Wind direction, speed, gust
        VVVV            ← Visibility (meters) or CAVOK
        w'w'            ← Weather phenomena
        NsNshshshs      ← Cloud cover, height
        
        [Change groups - remaining ≤6h]
        BECMG YYgg/YYgg ← Becoming (progressive change)
        TEMPO YYgg/YYgg ← Temporary (interruptions)
        FM YYGGgg       ← From (complete change)
        PROB30|40 TEMPO ← Probability (30 or 40% likelihood)
        ```
        """)
    
    with col2:
        st.subheader("Validation Stages")
        st.markdown("""
        **Stage 1: Format & Syntax**
        - Header: TAF/AMD/COR CCCC YYGGggZ
        - Validity: YYgg/YYgg (DDHHSS/DDHHSS)
        - Groups: syntax correctness
        - Codes: valid weather, cloud, etc.
        
        **Stage 2: Temporal**
        - Issue time ≤1h before validity
        - Duration 12-30 hours
        - Sequential change groups
        
        **Stage 3: Meteorological**
        - Wind: 0-360°, 0-230kt
        - VIS: 50m-10km, correct steps
        - Weather: logical codes
        - Cloud: heights at 30/60/150/300/450m
        - Change thresholds (wind ±60°/±10kt)
        
        **Stage 4: Consistency**
        - BECMG ≠ FM
        - PROB only with TEMPO
        - No duplicate time windows
        - Logical correlations
        """)
    
    st.divider()
    
    with st.expander("📐 Quy tắc chi tiết (1656/QĐ-CHK)"):
        st.markdown("""
        ### Nhóm Gió (Wind group)
        - **Format**: dddffGfmfmKT
        - **ddd**: Direction (000-360°), làm tròn 10°
        - **ff**: Speed (2 digits), knots
        - **Gfmfm**: Gust (nếu max speed ≥ avg + 10kt)
        - **VRB**: Variable direction (gió yếu hoặc dao động ≥180°)
        - **00000KT**: Calm wind
        - **P99KT**: Wind speed ≥100kt
        
        ### Nhóm Tầm nhìn (Visibility)
        - **Format**: VVVV (4 digits in meters)
        - **Steps**:
          - <800m: 50m (0050, 0100, 0150, ..., 0750)
          - 800-5000m: 100m (0800, 0900, 1000, ..., 4900)
          - ≥5000m: 1km (5000, 6000, ..., 9999)
        - **CAVOK**: VIS ≥10km + no weather + no low clouds + NSW
        
        ### Hiện tượng thời tiết (Weather)
        - **Precipitation**: RA, SN, DZ (với +, -, hoặc không)
        - **Freezing**: FZRA, FZDZ, FZFG
        - **Storms**: TS, TSRA, +TSRA, TSGR
        - **Other**: FG, BR, HZ, FU, BLDU, BLSA, SS, DS, FC, SQ
        - **Max 3 phenomena** per group
        
        ### Nhóm Mây (Cloud/Vertical visibility)
        - **Cover codes**:
          - SKC: Sky clear (special case)
          - CLR: Clear (no clouds)
          - FEW: 1-2/8
          - SCT: 3-4/8
          - BKN: 5-7/8
          - OVC: 8/8 (overcast)
          - NSC: Nil significant cloud
          - NCD: No cloud detected
        - **Height format**: hshshs (3 digits = hundreds of feet)
        - **Heights in meters**: 30, 60, 150, 300, 450
        - **Special types**: CB (Cumulonimbus), TCU (Towering Cumulus)
        
        ### Nhóm Biến đổi (Change groups)
        
        **BECMG (Becoming)**
        - Sự thay đổi dần dần trong 2-4 giờ
        - Format: BECMG YYgg/YYgg [changes]
        - Chỉ đưa ra những yếu tố thay đổi ≥ ngưỡng
        
        **TEMPO (Temporary)**
        - Dao động tạm thời < 1h mỗi lần
        - Tổng thời gian < 1/2 kỳ dự báo
        - Format: TEMPO YYgg/YYgg [changes]
        
        **FM (From)**
        - Sự thay đổi đáng kể, lập tức
        - Format: FM YYGGgg [full update]
        - Phải cập nhật TẤT CẢ các yếu tố
        
        **PROB (Probability)**
        - Chỉ với TEMPO, KHÔNG dùng BECMG
        - Format: PROB30 TEMPO ... hoặc PROB40 TEMPO ...
        - Xác suất 30% hoặc 40%
        
        ### Tiêu chí Thay đổi (Change criteria - 1656 mục 3.3)
        
        **Gió**
        - Hướng thay đổi ≥60° với tốc độ ≥10kt trước/sau
        - Tốc độ thay đổi ≥10kt
        - Gust thay đổi ≥10kt (với avg wind ≥15kt)
        - Vượt ngưỡng khai thác sân bay
        
        **Tầm nhìn**
        - Thay đổi qua ngưỡng: 150, 350, 600, 800, 1500, 3000, 5000m
        - 5000m chỉ áp dụng nếu sân bay có VFR traffic
        
        **Hiện tượng thời tiết**
        - Bắt đầu/kết thúc: FZRA, FZDZ, FZFG, TSRA, TSGR, RA (≥moderate)
        - Thay đổi cường độ: các hiện tượng trên
        - Bắt đầu/kết thúc: BLDU, BLSA, BLSN, SQ, FC
        
        **Mây**
        - Độ cao chân mây BKN/OVC thấp nhất thay đổi qua: 30, 60, 150, 300, 450m
        - Cover thay đổi từ NSC/FEW/SCT ↔ BKN/OVC (dưới 450m)
        """)
    
    st.divider()
    
    with st.expander("🔗 Các tài liệu tham chiếu"):
        st.markdown("""
        ### Vietnamese Regulations
        - **1656/QĐ-CHK** (10/8/2023): Hướng dẫn Bản tin khí tượng hàng không
          - Chương IV: TAF, TAF AMD
          - Phụ lục 3: Tiêu chí dự báo
          - Phụ lục 4: Giải thích hiện tượng
        
        ### ICAO International Standards
        - **ICAO Doc 10157** (2021): Aeronautical Meteorology Manual (PANS-MET)
          - Section 3.2: TAF structure and codes
        - **ICAO Annex 3** Amendment 82 (2025): Meteorological Service
          - Part A3: TAF requirements
        - **WMO-306** Part I.1 (2019): Manual on Codes
        
        ### Regional
        - **Asia-Pacific Regional Sigmet Guide** (2022): For SIGMET context
        - **APAC ANP** (2022): Regional Air Navigation Plan
        """)

# Footer
st.divider()
st.markdown("""
<div style="text-align: center; color: #666; font-size: 0.9em; margin-top: 30px;">
    <p>TAF Validation System v1.0 | Based on 1656/QĐ-CHK, ICAO Doc 10157, Annex 3 Amendment 82</p>
    <p>For official TAF validation, always refer to official meteorological authorities</p>
</div>
""", unsafe_allow_html=True)
