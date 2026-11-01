"""app.py - 第6章:Streamlit 使用者介面(風格 A:儀表板)

啟動:streamlit run app.py
(本機需要先啟動 FastAPI:python -m uvicorn main:app --reload;
 沒有另外啟動時,會自動改用「內建 API 模式」,見 start_embedded_api)
"""
import os
import random
import re
import sys

import pandas as pd
import requests
import streamlit as st

API = os.environ.get("API_URL", "http://127.0.0.1:8000")  # 雲端部署時可由環境變數指定
FEATURE_LABELS = {"danceability": "舞動性", "energy": "能量", "valence": "情緒", "acousticness": "原聲度"}
METHODS = {"hybrid": "混合", "cf": "協同過濾", "content": "音樂特徵"}

# 以下數字來自 etl_real.py 與 evaluate.py 的實際執行結果
PIPELINE_SONGS = [
    ("Spotify 檔案列數", 114000, "同一首歌被歸在多個曲風時會重複出現"),
    ("不重複的 track_id", 89741, "去掉曲風造成的重複"),
    ("不重複的「歌名 + 歌手」", 81344, "去掉同名同歌手但 track_id 不同的版本"),
    ("正規化後的比對鍵", 80052, "統一大小寫、括號、符號後再去重複"),
    ("與 Million Song Dataset 比對成功", 12510, "比對上才有聆聽紀錄可用"),
    ("取聆聽最多的 3,000 首並抽樣使用者後", 2832, "最終匯入資料庫;抽樣後沒有人聽的歌會被剔除"),
]
PIPELINE_PLAYS = [
    ("Taste Profile 全部聆聽紀錄", 48373586, "使用者、歌曲、播放次數"),
    ("比對成功歌曲的聆聽紀錄", 6072669, "只保留有 Spotify 特徵的歌"),
    ("最終匯入資料庫", 59379, "熱門 3,000 首歌;在這些歌裡至少聽過 5 首的使用者,隨機抽 5,000 位"),
]
EVAL_ROWS = [  # 方法, Precision@10, Recall@10, HitRate@10, 相對熱門排行
    ("random(亂猜)", 0.0009, 0.0040, 0.0087, "—"),
    ("popular(熱門排行,基準線)", 0.0235, 0.0903, 0.1681, "基準"),
    ("cf(協同過濾)", 0.0493, 0.2093, 0.3559, "+109.8%"),
    ("content(音樂特徵)", 0.0017, 0.0073, 0.0169, "−92.7%"),
    ("hybrid(混合)", 0.0319, 0.1333, 0.2462, "+35.6%"),
]

GLOSSARY = """
**推薦方法**
- **混合**:綜合「聽的人重疊」與「聲音相近」兩種線索(協同過濾佔 60%、音樂特徵佔 40%)
- **協同過濾**:常被同一批人聽的歌,視為互相相似
- **音樂特徵**:聲音特徵(下方四項)接近的歌,視為互相相似

**音樂特徵**(數值都在 0 到 1 之間,來自 Spotify)
- **舞動性**:適合跳舞的程度,依節奏穩定度、拍子強度等判斷
- **能量**:強烈、熱鬧的程度,越高越快、越大聲、越吵
- **情緒**:音樂傳達的正向程度,越高越開心明亮,越低越憂傷
- **原聲度**:越高,越有把握是原聲(非電子)風格的歌

**相似度**:分數越高越相似,只用來比較排序,數字本身不是百分比。
"""

st.set_page_config(page_title="音樂搜尋與推薦", page_icon="🎵", layout="wide")


def esc(s):
    """跳脫 Markdown 特殊符號,避免歌名中的 * _ $ 等被誤判成格式。"""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!$~|<>])", r"\\\1", str(s))


@st.cache_resource(show_spinner="第一次啟動,正在載入資料並啟動內建 API ...")
def start_embedded_api():
    """沒有另外啟動 FastAPI 時(例如部署在 Streamlit Community Cloud),
    就在同一個程式裡用背景執行緒啟動它。本機照 README 開兩個終端機時不會用到這段。"""
    import threading
    import time
    import urllib.request

    import uvicorn

    try:
        import main  # 載入資料庫並計算相似度
    except BaseException as e:  # main.py 找不到資料庫時會 SystemExit
        return f"無法載入 main.py:{e}"
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=8000, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(120):
        try:
            urllib.request.urlopen(f"{API}/popular?limit=1", timeout=2)
            return None
        except Exception:
            time.sleep(0.5)
    return "內建 API 啟動逾時"


@st.cache_data(ttl=60)
def call(path, **params):
    """呼叫 FastAPI,結果快取 60 秒。"""
    r = requests.get(f"{API}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def show_songs(rows, with_score=False, plays_key="total_plays", plays_label="總播放數"):
    """把歌曲清單畫成表格;推薦結果的相似度以長條顯示。"""
    df = pd.DataFrame(rows)
    out = pd.DataFrame({"排名": range(1, len(df) + 1), "歌名": df["title"], "歌手": df["artist"]})
    if plays_key in df:
        out[plays_label] = df[plays_key]
    config = {}
    if with_score and "score" in df:
        out["相似度"] = df["score"]
        config["相似度"] = st.column_config.ProgressColumn(
            "相似度", help="分數越高越相似,只用來比較排序", min_value=0.0,
            max_value=float(df["score"].max()) or 1.0, format="%.3f")
    st.dataframe(out, column_config=config, width="stretch", hide_index=True)


def pick_method(key):
    """推薦方法選擇(新版 Streamlit 用並排按鈕,舊版退回單選鈕)。"""
    seg = getattr(st, "segmented_control", None)
    if seg:
        return seg("推薦方法", list(METHODS), default="hybrid", format_func=METHODS.get,
                   key=key, label_visibility="collapsed") or "hybrid"
    return st.radio("推薦方法", list(METHODS), format_func=METHODS.get, horizontal=True, key=key)


st.title("🎵 音樂搜尋與推薦系統")
st.caption("輸入歌名或歌手,找出相似的歌;也可以選一位使用者,看系統會推薦他什麼歌。")

try:
    call("/popular", limit=1)
except requests.exceptions.ConnectionError:
    err = start_embedded_api() if API.startswith("http://127.0.0.1") else "API_URL 指定的 FastAPI 連不上"
    if err:
        st.error(f"連不上 FastAPI。{err}\n\n本機請先在另一個終端機執行:python -m uvicorn main:app --reload")
        st.stop()
    call("/popular", limit=1)

if "main" in sys.modules:
    st.caption("ℹ️ 目前使用「內建 API 模式」:FastAPI 與網頁在同一個程式中執行。")

# ---------- 頂端:資料概況卡片 ----------
try:
    stats = call("/stats")
except requests.exceptions.RequestException:
    stats = None  # 舊版 API 沒有 /stats,就不顯示卡片
if stats:
    for col, (label, key) in zip(st.columns(4), [("歌曲", "songs"), ("歌手", "artists"),
                                                  ("使用者", "users"), ("聆聽紀錄", "plays")]):
        with col.container(border=True):
            st.metric(label, f"{stats[key]:,}")
    st.caption("資料只包含「同時有聆聽紀錄與 Spotify 音樂特徵」的歌曲,所以歌曲數比原始資料集少。")

with st.expander("名詞說明(點開查看)"):
    st.markdown(GLOSSARY)

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🔍 搜尋與相似歌曲", "👤 使用者推薦", "🔥 熱門歌曲", "🎤 歌手排行", "📊 系統評估"])

# ---------- 分頁1:搜尋 -> 選一首 -> 歌曲卡片與相似歌曲 ----------
with tab1:
    q = st.text_input("搜尋歌名或歌手", placeholder="輸入歌名或歌手,例如:Neon、Coldplay")
    if q:
        results = call("/search", q=q, limit=10000)  # 不設上限(資料庫總共才約三千首歌)
        if not results:
            st.warning("找不到符合的歌曲")
        else:
            st.caption(f"找到 {len(results)} 首" + ("(結果很多,輸入更完整的歌名或歌手可以縮小範圍)" if len(results) > 200 else ""))
            label = {f"{s['title']} - {s['artist']}": s for s in results}
            song = label[st.selectbox("選一首歌,查看詳細資料與相似歌曲", list(label))]
            left, right = st.columns([5, 7])
            with left, st.container(border=True):
                st.subheader(esc(song["title"]))
                st.caption(f"{esc(song['artist'])} · 總播放 {song['total_plays']:,} 次 · {song['tempo']:.0f} BPM")
                feat = pd.DataFrame({"特徵": list(FEATURE_LABELS.values()),
                                     "數值": [min(max(float(song[k]), 0.0), 1.0) for k in FEATURE_LABELS]})
                st.dataframe(feat, hide_index=True, width="stretch", column_config={
                    "數值": st.column_config.ProgressColumn("數值", min_value=0.0, max_value=1.0, format="%.2f")})
            with right, st.container(border=True):
                st.markdown("**相似歌曲**")
                method = pick_method("song_method")
                show_songs(call(f"/recommend/song/{song['song_id']}", k=10, method=method), with_score=True)
    else:
        st.caption("輸入歌名或歌手開始搜尋,例如 Coldplay、Neon。先看看目前最熱門的歌曲:")
        show_songs(call("/popular", limit=10))

# ---------- 分頁2:選使用者 -> 聆聽紀錄與推薦 ----------
with tab2:
    all_users = call("/users")

    def pick_random_user():
        """隨機挑一位聽過至少 10 首歌的使用者(紀錄太少的使用者展示效果不好)。"""
        pool = call("/users", min_plays=10) or all_users
        st.session_state["uid_sel"] = random.choice(pool)

    c_sel, c_btn = st.columns([4, 1], vertical_alignment="bottom")
    uid = c_sel.selectbox("選擇使用者", all_users, key="uid_sel")
    c_btn.button("🎲 隨機挑一位", on_click=pick_random_user, width="stretch")
    k = st.slider("推薦幾首", 5, 20, 10)
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.markdown("**聽最多的歌**")
        show_songs(call(f"/users/{uid}/history", limit=10), plays_key="play_count", plays_label="播放次數")
    with right, st.container(border=True):
        st.markdown("**為你推薦(還沒聽過的歌)**")
        method = pick_method("user_method")
        show_songs(call(f"/recommend/user/{uid}", k=k, method=method), with_score=True)

# ---------- 分頁3:熱門排行 ----------
with tab3:
    n = st.slider("顯示前幾名", 5, 30, 10, key="pop")
    pop = pd.DataFrame(call("/popular", limit=n))
    st.bar_chart(pop.set_index("title")["total_plays"])
    show_songs(pop.to_dict("records"))

# ---------- 分頁4:歌手排行(依歌曲數)----------
with tab4:
    n_art = st.slider("顯示前幾位歌手", 5, 30, 15, key="art_n")
    try:
        arts = call("/artists", limit=n_art)
    except requests.exceptions.RequestException:
        arts = None
        st.info("這個分頁需要更新版的 main.py(多了 /artists 端點)。")
    if arts:
        adf = pd.DataFrame(arts)
        st.dataframe(
            pd.DataFrame({"排名": adf["rank"], "歌手": adf["artist"], "歌曲數": adf["songs"],
                          "總播放數": adf["total_plays"]}),
            column_config={"歌曲數": st.column_config.ProgressColumn(
                "歌曲數", min_value=0, max_value=int(adf["songs"].max()), format="%d")},
            width="stretch", hide_index=True)
        who = st.selectbox("選一位歌手,查看他的歌曲(依總播放數由高到低)", adf["artist"])
        with st.container(border=True):
            st.markdown(f"**{esc(who)} 的歌曲**")
            show_songs(call("/artist-songs", name=who))

# ---------- 分頁5:資料處理與推薦評估(靜態說明)----------
with tab5:
    st.subheader("資料處理:從 11.4 萬列縮小到 2,832 首歌")
    st.caption("資料庫只保留「同時有聆聽紀錄與 Spotify 音樂特徵」的歌曲,兩份資料年代不同,重疊有限。")
    sdf = pd.DataFrame(PIPELINE_SONGS, columns=["階段", "歌曲數", "說明"])
    st.dataframe(sdf, hide_index=True, width="stretch", column_config={
        "歌曲數": st.column_config.ProgressColumn("歌曲數", min_value=0, max_value=114000, format="%d")})
    pdf = pd.DataFrame(PIPELINE_PLAYS, columns=["聆聽紀錄", "筆數", "說明"])
    st.dataframe(pdf, hide_index=True, width="stretch", column_config={
        "筆數": st.column_config.NumberColumn("筆數", format="%d")})

    st.subheader("推薦演算法的離線評估")
    st.caption("方法:對每位使用者藏起約 20% 聽過的歌當標準答案,用其餘紀錄建模後推薦 10 首,看猜中幾首;"
               "5,000 位使用者全數納入測試,重複 3 次取平均。")
    edf = pd.DataFrame(EVAL_ROWS, columns=["方法", "Precision@10", "Recall@10", "HitRate@10", "相對熱門排行"])
    st.dataframe(edf, hide_index=True, width="stretch", column_config={
        "Precision@10": st.column_config.ProgressColumn("Precision@10", help="推薦的 10 首裡猜中的比例",
                                                         min_value=0.0, max_value=0.06, format="%.4f"),
        "Recall@10": st.column_config.NumberColumn("Recall@10", help="被藏起來的歌被找回的比例", format="%.4f"),
        "HitRate@10": st.column_config.NumberColumn("HitRate@10", help="至少猜中 1 首的使用者比例", format="%.4f")})
    st.bar_chart(edf.set_index("方法")["Precision@10"])
    st.markdown(
        "- **協同過濾最好**:Precision@10 約為熱門排行的 2.1 倍,約 36% 的使用者在推薦的 10 首裡至少猜中 1 首。\n"
        "- **音樂特徵單獨使用效果差**;混合推薦勝過熱門排行,但不如單用協同過濾。\n"
        "- 評估只衡量「是否猜中他實際聽過的歌」,沒聽過不代表不喜歡,所以分數偏低是正常的,重點看方法之間的相對高低。")

