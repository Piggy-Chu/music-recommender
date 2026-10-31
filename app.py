"""app.py - 第6章:Streamlit 使用者介面

啟動:streamlit run app.py
(需要先啟動 FastAPI:uvicorn main:app --reload)
"""
import pandas as pd
import requests
import streamlit as st

API = "http://127.0.0.1:8000"
COLS = {"title": "歌名", "artist": "歌手", "year": "年份", "total_plays": "總播放數", "score": "推薦分數"}

st.set_page_config(page_title="音樂搜尋與推薦", page_icon="🎵", layout="wide")
st.title("🎵 音樂搜尋與推薦系統")


@st.cache_data(ttl=60)
def call(path, **params):
    """呼叫 FastAPI,結果快取 60 秒。"""
    r = requests.get(f"{API}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def table(rows):
    df = pd.DataFrame(rows)
    cols = [c for c in COLS if c in df.columns]
    st.dataframe(df[cols].dropna(axis=1, how="all").rename(columns=COLS), width="stretch", hide_index=True)


try:
    call("/popular", limit=1)
except requests.exceptions.ConnectionError:
    st.error("連不上 FastAPI。請先在另一個終端機執行:uvicorn main:app --reload")
    st.stop()

tab1, tab2, tab3 = st.tabs(["🔍 搜尋與相似歌曲", "👤 使用者推薦", "🔥 熱門歌曲"])

# ---------- 分頁1:搜尋 -> 選一首 -> 看特徵與相似歌曲 ----------
with tab1:
    q = st.text_input("輸入歌名或歌手", placeholder="例如:Neon、Band 5")
    if q:
        results = call("/search", q=q, limit=30)
        if not results:
            st.warning("找不到符合的歌曲")
        else:
            st.caption(f"找到 {len(results)} 首(最多顯示 30 首)")
            table(results)
            label = {f"{s['title']} - {s['artist']}": s for s in results}
            song = label[st.selectbox("選一首歌,查看詳細資料與相似歌曲", list(label))]
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("音樂特徵")
                st.bar_chart(pd.Series({k: song[k] for k in ["danceability", "energy", "valence", "acousticness"]}))
                st.metric("節奏 (BPM)", song["tempo"])
            with c2:
                st.subheader("相似歌曲")
                method = st.radio("推薦方法", ["hybrid", "cf", "content"], horizontal=True,
                                  format_func={"hybrid": "混合", "cf": "協同過濾", "content": "音樂特徵"}.get)
                table(call(f"/recommend/song/{song['song_id']}", k=10, method=method))

# ---------- 分頁2:選使用者 -> 看聆聽紀錄與推薦 ----------
with tab2:
    uid = st.selectbox("選擇使用者", call("/users"))
    k = st.slider("推薦幾首", 5, 20, 10)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("聽最多的歌")
        h = pd.DataFrame(call(f"/users/{uid}/history", limit=10))
        st.dataframe(h[["title", "artist", "play_count"]].rename(
            columns={**COLS, "play_count": "播放次數"}), width="stretch", hide_index=True)
    with c2:
        st.subheader("為你推薦(還沒聽過的歌)")
        table(call(f"/recommend/user/{uid}", k=k))

# ---------- 分頁3:熱門排行 ----------
with tab3:
    n = st.slider("顯示前幾名", 5, 30, 10, key="pop")
    pop = pd.DataFrame(call("/popular", limit=n))
    st.bar_chart(pop.set_index("title")["total_plays"])
    table(pop.to_dict("records"))
