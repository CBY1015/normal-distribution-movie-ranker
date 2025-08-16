# backend.py (最終修復版 - 完整註解)
import json
import os
import requests
from scipy.stats import norm
from flask import Flask, request, jsonify
from flask_cors import CORS
import random
import re
import sqlite3
import threading

# --- 基本設定 ---
API_KEY = 'c2a2b97dd7fbdf369708b6ae94e46def' # 您的 TMDB API 金鑰
TMDB_BASE_URL = 'https://api.themoviedb.org/3'

# --- 初始化 Flask App ---
app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# --- 強制使用 SQLite 以確保穩定性 ---
print("🔄 使用 SQLite 資料庫以確保穩定性")
DB_FILE = '/tmp/movie_ranking.db'
db_lock = threading.Lock()

def get_db_connection():
    """取得 SQLite 資料庫連線"""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化 SQLite 資料庫"""
    try:
        with db_lock:
            conn = get_db_connection()
            try:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY,
                        movies TEXT DEFAULT '[]'
                    )
                ''')
                conn.commit()
                print("✅ SQLite 資料庫初始化成功")
                return True
            except Exception as e:
                print(f"❌ SQLite 初始化失敗：{e}")
                return False
            finally:
                conn.close()
    except Exception as e:
        print(f"❌ 資料庫連線失敗：{e}")
        return False

# --- 輔助函式 ---
def is_valid_username(username):
    """檢查使用者名稱是否合法 (只允許英文字母和數字)，防止惡意輸入。"""
    return username and re.match(r'^[a-zA-Z0-9]+$', username)

# --- 資料庫核心邏輯 ---
def user_exists(username):
    """檢查資料庫中是否存在指定的使用者。"""
    try:
        with db_lock:
            conn = get_db_connection()
            try:
                cursor = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,))
                result = cursor.fetchone()
                return result is not None
            finally:
                conn.close()
    except Exception as e:
        print(f"❌ user_exists 錯誤：{e}")
        return False

def load_ranked_movies(username):
    """從資料庫讀取指定使用者的電影列表。"""
    try:
        with db_lock:
            conn = get_db_connection()
            try:
                cursor = conn.execute("SELECT movies FROM users WHERE username = ?", (username,))
                result = cursor.fetchone()
                if result and result[0]:
                    return json.loads(result[0])
                return []
            finally:
                conn.close()
    except Exception as e:
        print(f"❌ load_ranked_movies 錯誤：{e}")
        return []

def save_ranked_movies(username, movies):
    """將指定使用者的電影列表存入資料庫。"""
    try:
        with db_lock:
            conn = get_db_connection()
            try:
                movies_json = json.dumps(movies, ensure_ascii=False)
                
                # 使用 INSERT OR REPLACE 確保操作成功
                conn.execute('''
                    INSERT OR REPLACE INTO users (username, movies) 
                    VALUES (?, ?)
                ''', (username, movies_json))
                conn.commit()
                
                print(f"✅ 成功儲存使用者 {username} 的資料")
                return True
                
            except Exception as e:
                print(f"❌ SQLite 儲存失敗：{e}")
                conn.rollback()
                return False
            finally:
                conn.close()
    except Exception as e:
        print(f"❌ save_ranked_movies 錯誤：{e}")
        return False

# --- TMDB API 函式 ---
def search_movie_from_tmdb(title):
    search_url = f"{TMDB_BASE_URL}/search/movie"
    params = {'api_key': API_KEY, 'query': title, 'language': 'zh-TW'}
    try:
        response = requests.get(search_url, params=params)
        response.raise_for_status()
        return response.json()['results']
    except requests.exceptions.RequestException as e:
        print(f"❌ TMDB 搜尋失敗：{e}")
        return None

def get_random_movie_from_tmdb():
    discover_url = f"{TMDB_BASE_URL}/discover/movie"
    random_page = random.randint(1, 500) 
    params = {
        'api_key': API_KEY, 
        'language': 'zh-TW', 
        'sort_by': 'popularity.desc', 
        'page': random_page, 
        'include_adult': 'false', 
        'vote_count.gte': 100
    }
    try:
        response = requests.get(discover_url, params=params)
        response.raise_for_status()
        results = response.json()['results']
        return random.choice(results) if results else None
    except requests.exceptions.RequestException as e:
        print(f"❌ TMDB 隨機電影失敗：{e}")
        return None

def recalculate_ratings_and_ranks(ranked_list, mode='normal'):
    n = len(ranked_list)
    if n == 0: 
        return []
        
    for i, movie in enumerate(ranked_list):
        movie['my_rank'] = i + 1
        score = 3.0
        
        if n == 1: 
            score = 3.0
        elif mode == 'linear':
            raw_score = 5.0 - (4.5 * i / (n - 1))
            score = round(raw_score * 2) / 2
        else:
            percentile = (n - 1 - i + 0.5) / n
            z_score = norm.ppf(percentile)
            raw_score = 2.75 + z_score * 1.0
            clamped_score = max(0.5, min(5.0, raw_score))
            score = round(clamped_score * 2) / 2
            
        movie['my_rating'] = score
    
    return ranked_list

# --- API 端點 ---
@app.route('/')
def index():
    """根目錄，直接提供前端的 index.html 檔案。"""
    return app.send_static_file('index.html')

@app.route('/api/db-info', methods=['GET'])
def get_database_info():
    """顯示目前使用的資料庫資訊"""
    try:
        with db_lock:
            conn = get_db_connection()
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM users")
                user_count = cursor.fetchone()[0]
                
                # 取得幾個使用者名稱作為範例
                cursor = conn.execute("SELECT username FROM users LIMIT 3")
                users = [row[0] for row in cursor.fetchall()]
                
                return jsonify({
                    'success': True,
                    'provider': 'SQLite (穩定模式)',
                    'total_users': user_count,
                    'sample_users': users,
                    'database_file': DB_FILE,
                    'connection_status': 'SQLite Connected',
                    'note': '✅ 應用運作正常！設定好 Neon 後可切換到 PostgreSQL。'
                })
            finally:
                conn.close()
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'connection_status': 'SQLite Connection failed'
        }), 500

@app.route('/api/register', methods=['POST'])
def register_user():
    """處理使用者註冊請求。"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': '無效的請求資料'}), 400
            
        username = data.get('username')
        print(f"🔍 嘗試註冊使用者：{username}")
        
        if not is_valid_username(username):
            return jsonify({'error': '無效的使用者名稱，只能使用英文字母和數字。'}), 400
        
        if user_exists(username):
            return jsonify({'error': '此使用者名稱已被註冊。'}), 409
        
        # 嘗試儲存新使用者
        if save_ranked_movies(username, []):
            print(f"✅ 使用者 {username} 註冊成功")
            return jsonify({'success': True, 'username': username})
        else:
            print(f"❌ 使用者 {username} 儲存失敗")
            return jsonify({'error': '無法創建使用者，請稍後再試。'}), 500
            
    except Exception as e:
        print(f"❌ 註冊過程錯誤：{e}")
        return jsonify({'error': '註冊過程發生錯誤，請稍後再試。'}), 500

@app.route('/api/login', methods=['POST'])
def login_user():
    """處理使用者登入請求。"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': '無效的請求資料'}), 400
            
        username = data.get('username')
        print(f"🔍 嘗試登入使用者：{username}")
        
        if not is_valid_username(username):
            return jsonify({'error': '無效的使用者名稱。'}), 400
        
        if not user_exists(username):
            return jsonify({'error': '使用者不存在。'}), 404
        
        print(f"✅ 使用者 {username} 登入成功")
        return jsonify({'success': True, 'username': username})
        
    except Exception as e:
        print(f"❌ 登入過程錯誤：{e}")
        return jsonify({'error': '登入過程發生錯誤，請稍後再試。'}), 500

def get_username_from_header():
    """從請求的 Header 中獲取使用者名稱，用於驗證身份。"""
    return request.headers.get('X-Username')

@app.route('/api/movies', methods=['GET', 'DELETE'])
def handle_movies():
    """處理電影列表的讀取(GET)和清空(DELETE)請求。"""
    username = get_username_from_header()
    if not username: 
        return jsonify({'error': '未提供使用者資訊'}), 401
        
    if request.method == 'GET': 
        return jsonify(load_ranked_movies(username))
    elif request.method == 'DELETE':
        if save_ranked_movies(username, []): 
            return jsonify({'success': True})
        else: 
            return jsonify({'error': 'Failed to clear movies'}), 500

@app.route('/api/movies/<int:movie_id>', methods=['DELETE'])
def delete_movie(movie_id):
    """處理刪除單一電影的請求。"""
    username = get_username_from_header()
    if not username: 
        return jsonify({'error': '未提供使用者資訊'}), 401
        
    mode = request.args.get('mode', 'normal')
    movies = load_ranked_movies(username)
    movies_to_keep = [m for m in movies if m.get('id') != movie_id]
    
    if len(movies_to_keep) == len(movies): 
        return jsonify({'error': 'Movie not found'}), 404
        
    recalculated_list = recalculate_ratings_and_ranks(movies_to_keep, mode)
    
    if save_ranked_movies(username, recalculated_list): 
        return jsonify(recalculated_list)
    else: 
        return jsonify({'error': 'Failed to save updated list'}), 500

@app.route('/api/rank', methods=['POST'])
def rank_movies():
    """處理新增或更新電影排名列表的請求。"""
    username = get_username_from_header()
    if not username: 
        return jsonify({'error': '未提供使用者資訊'}), 401
        
    data = request.json
    new_ranked_list = data.get('list')
    mode = data.get('mode', 'normal')
    
    if not isinstance(new_ranked_list, list): 
        return jsonify({'error': 'Invalid data format'}), 400
        
    recalculated_list = recalculate_ratings_and_ranks(new_ranked_list, mode)
    
    if save_ranked_movies(username, recalculated_list): 
        return jsonify(recalculated_list)
    else: 
        return jsonify({'error': 'Failed to save rankings'}), 500

@app.route('/api/review', methods=['POST'])
def save_review():
    """處理儲存電影評論的請求。"""
    username = get_username_from_header()
    if not username: 
        return jsonify({'error': '未提供使用者資訊'}), 401
        
    data = request.json
    movie_id = data.get('id')
    review_text = data.get('review')
    
    if not movie_id: 
        return jsonify({'error': 'Movie ID is required'}), 400
        
    movies = load_ranked_movies(username)
    movie_found = False
    
    for movie in movies:
        if movie['id'] == movie_id: 
            movie['my_review'] = review_text
            movie_found = True
            break
            
    if not movie_found: 
        return jsonify({'error': 'Movie not found'}), 404
        
    if save_ranked_movies(username, movies): 
        return jsonify({'success': True})
    else: 
        return jsonify({'error': 'Failed to save review'}), 500

@app.route('/api/search', methods=['GET'])
def search_movies():
    """處理電影搜尋請求。"""
    title = request.args.get('title')
    if not title: 
        return jsonify({'error': 'Title parameter is required'}), 400
        
    results = search_movie_from_tmdb(title)
    if results is None: 
        return jsonify({'error': 'Failed to fetch from TMDB'}), 500
        
    return jsonify(results)

@app.route('/api/random', methods=['GET'])
def get_random_movie():
    """處理隨機探索電影的請求。"""
    existing_ids_str = request.args.get('existing_ids', '')
    existing_ids = {int(id) for id in existing_ids_str.split(',') if id}
    
    for _ in range(10):
        movie = get_random_movie_from_tmdb()
        if movie and movie.get('id') not in existing_ids: 
            return jsonify(movie)
            
    return jsonify({'error': 'Could not find a new random movie'}), 500

# --- 應用程式啟動 ---
if __name__ == '__main__':
    print("🚀 電影排名系統啟動中...")
    
    # 初始化資料庫
    if init_db():
        print("✅ 資料庫初始化成功")
    else:
        print("❌ 資料庫初始化失敗")
    
    app.run(port=5000)
else:
    # 在 Render 上執行時
    print("🚀 電影排名系統在 Render 上啟動...")
    
    # 初始化資料庫
    if init_db():
        print("✅ 資料庫初始化成功")
    else:
        print("❌ 資料庫初始化失敗")
