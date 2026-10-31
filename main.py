"""main.py - 第5章:FastAPI 音樂搜尋與推薦

啟動:uvicorn main:app --reload
API 文件(可直接點擊測試):http://127.0.0.1:8000/docs

推薦演算法:
  cf      協同過濾(item-based):常被「同一批人」聽的歌互相相似
  content 內容導向:Spotify 音樂特徵(舞動性、能量、情緒...)相近的歌互相相似
  hybrid  兩者加權平均(預設)
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from sklearn.metrics.pairwise import cosine_similarity

DB_PATH = Path(__file__).parent / "db" / "music.db"
FEATURES = ["danceability", "energy", "valence", "acousticness", "tempo"]

if not DB_PATH.exists():
    raise SystemExit("找不到 db/music.db,請先執行:python etl.py")

# ---------- 啟動時把資料讀進記憶體並算好相似度 ----------
con = sqlite3.connect(DB_PATH)
songs = pd.read_sql(
    "SELECT s.song_id, s.title, a.name AS artist, s.year, "
    "f.danceability, f.energy, f.valence, f.acousticness, f.tempo "
    "FROM song s JOIN artist a ON a.artist_id = s.artist_id "
    "JOIN spotify_feature f ON f.song_id = s.song_id ORDER BY s.song_id", con)
plays = pd.read_sql("SELECT user_id, song_id, play_count FROM listening", con)
con.close()

song_idx = {sid: i for i, sid in enumerate(songs.song_id)}
plays = plays[plays.song_id.isin(song_idx)]
user_ids = sorted(plays.user_id.unique())
user_idx = {uid: i for i, uid in enumerate(user_ids)}

# 使用者 x 歌曲 矩陣(播放次數取 log,避免少數超高次數主導)
M = np.zeros((len(user_ids), len(songs)))
M[plays.user_id.map(user_idx).to_numpy(), plays.song_id.map(song_idx).to_numpy()] = np.log1p(
    plays.play_count.to_numpy())

cf_sim = cosine_similarity(M.T)                                    # 歌 x 歌(協同過濾)
X = songs[FEATURES].to_numpy()
X = (X - X.mean(axis=0)) / X.std(axis=0)                           # 標準化,tempo 才不會壓過其他特徵
content_sim = (cosine_similarity(X) + 1) / 2                       # 轉成 0~1
SIM = {"cf": cf_sim, "content": content_sim, "hybrid": 0.6 * cf_sim + 0.4 * content_sim}
popularity = plays.groupby("song_id").play_count.sum()

app = FastAPI(title="Music Search & Recommend API")


def to_dict(i, score=None):
    r = songs.iloc[i]
    d = {"song_id": int(r.song_id), "title": r.title, "artist": r.artist, "year": int(r.year) if pd.notna(r.year) else None,
         "danceability": round(float(r.danceability), 3), "energy": round(float(r.energy), 3),
         "valence": round(float(r.valence), 3), "acousticness": round(float(r.acousticness), 3),
         "tempo": round(float(r.tempo), 1),
         "total_plays": int(popularity.get(r.song_id, 0))}
    if score is not None:
        d["score"] = round(float(score), 4)
    return d


def top_k(scores, k, exclude):
    scores = scores.copy()
    scores[list(exclude)] = -np.inf
    order = np.argsort(-scores)[:k]
    return [to_dict(i, scores[i]) for i in order if np.isfinite(scores[i])]


@app.get("/search")
def search(q: str, limit: int = 20):
    """用歌名或歌手模糊搜尋(不分大小寫)。"""
    m = songs.title.str.contains(q, case=False, regex=False) | songs.artist.str.contains(q, case=False, regex=False)
    return [to_dict(i) for i in np.flatnonzero(m.to_numpy())[:limit]]


@app.get("/songs/{song_id}")
def get_song(song_id: int):
    if song_id not in song_idx:
        raise HTTPException(404, "找不到這首歌")
    return to_dict(song_idx[song_id])


@app.get("/popular")
def popular(limit: int = 10):
    """依總播放次數排序的熱門歌曲。"""
    return [to_dict(song_idx[sid]) for sid in popularity.sort_values(ascending=False).index[:limit]]


@app.get("/recommend/song/{song_id}")
def recommend_by_song(song_id: int, k: int = 10, method: str = "hybrid"):
    """推薦相似歌曲。method = cf / content / hybrid"""
    if song_id not in song_idx:
        raise HTTPException(404, "找不到這首歌")
    if method not in SIM:
        raise HTTPException(400, "method 只能是 cf、content、hybrid")
    i = song_idx[song_id]
    return top_k(SIM[method][i], k, exclude=[i])


@app.get("/users")
def list_users():
    return [int(u) for u in user_ids]


@app.get("/users/{user_id}/history")
def user_history(user_id: int, limit: int = 10):
    """使用者聽最多的歌。"""
    if user_id not in user_idx:
        raise HTTPException(404, "找不到這位使用者")
    p = plays[plays.user_id == user_id].sort_values("play_count", ascending=False).head(limit)
    return [{**to_dict(song_idx[r.song_id]), "play_count": int(r.play_count)} for r in p.itertuples()]


@app.get("/recommend/user/{user_id}")
def recommend_by_user(user_id: int, k: int = 10, method: str = "hybrid"):
    """依使用者的聆聽紀錄推薦「還沒聽過」的歌。"""
    if user_id not in user_idx:
        raise HTTPException(404, "找不到這位使用者")
    if method not in SIM:
        raise HTTPException(400, "method 只能是 cf、content、hybrid")
    u = M[user_idx[user_id]]
    scores = u @ SIM[method]                       # 聽過的歌越多、越相似的歌分數越高
    return top_k(scores / (u.sum() or 1), k, exclude=np.flatnonzero(u))
