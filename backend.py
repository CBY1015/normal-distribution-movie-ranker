# backend.py (Neon 升級版 - 智能資料庫切換)
import json
import os
import requests
from scipy.stats import norm
from flask import Flask, request, jsonify
from flask_cors import CORS
import random
import re

# --- 基本設定 ---
API_KEY = 'c2a2b97dd7fbdf369708b6ae94e46def'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'

# --- 初始化 Flask App ---
app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# --- 智能資料庫選擇 ---
DATABASE_URL = os.environ.get('DATABASE_URL')
USE_SQLITE = False
engine = None

print(f"🔍 檢查 DATABASE_URL: {DATABASE_URL[:50] + '...' if DATABASE_URL and len(DATABASE_URL) > 50 else DATABASE_URL}")

try:
    # 檢查是否有有效的 DATABASE_URL
    if not DATABASE_URL or len(DATABASE_URL) < 10 or DATABASE_URL == 'None':
        raise Exception("DATABASE_URL 無效或未設定")
    
    # 嘗試連接 PostgreSQL (Neon)
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL)
    
    # 測試連線
    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).fetchone()
    
    # 判斷資料庫類型
    if "neon" in DATABASE_URL.lower():
        print("✅ 成功連接到 Neon PostgreSQL")
    elif "supabase" in DATABASE_URL.lower():
        print("✅ 成功連接到 Supabase PostgreSQL")
    else:
        print("✅ 成功連接到 PostgreSQL")
    
    USE_SQLITE = False
    
except Exception as e:
    print(f"⚠️ PostgreSQL 連線失敗：{e}")
    print("🔄 降級到 SQLite 備用模式...")
    USE_SQLITE = True
    
    # 匯入 SQLite 相關模組
    import sqlite3
    import threading
    
    DB_FILE = '/tmp/movie_ranking.db'
    db_lock = threading.Lock()

# --- 資料庫初始化函式 ---
def init_db():
    """初始化資料庫"""
    try:
        if USE_SQLITE:
            print("🔧 初始化 SQLite 資料庫...")
            with db_lock:
                conn = sqlite3.connect(DB_FILE, check_same_thread=False)
                conn.row_factory = sqlite3.Row
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
                finally:
                    conn.close()
        else:
            print("🔧 初始化 PostgreSQL 資料庫...")
            with engine.connect() as connection:
                connection.execute(text("""
                    CREATE TABLE IF NOT EXISTS users (
                        username VARCHAR(255) PRIMARY KEY,
                        movies JSONB DEFAULT '[]'::jsonb
                    );
                """))
                connection.commit()
                print("✅ PostgreSQL 資料庫初始化成功")
                return True
    except Exception as e:
        print(f"❌ 資料庫初始化失敗：{e}")
        return False

# --- 輔助函式 ---
def is_valid_username(username):
    """檢查使用者名稱是否合法"""
    return username and re.match(r'^[a-zA-Z0-9]+$', username)

# --- 資料庫操作函式 ---
def user_exists(username):
    """檢查使用者是否存在"""
    try:
        if USE_SQLITE:
            with db_lock:
                conn = sqlite3.connect(DB_FILE, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                try:
                    cursor = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,))
                    return cursor.fetchone() is not None
                finally:
                    conn.close()
        else:
            with engine.connect() as connection:
                result = connection.execute(text("SELECT 1 FROM users WHERE username = :user"), {"user": username}).fetchone()
                return result is not None
    except Exception as e:
        print(f"❌ user_exists 錯誤：{e}")
        return False

def load_ranked_movies(username):
    """讀取使用者的電影列表"""
    try:
        if USE_SQLITE:
            with db_lock:
                conn = sqlite3.connect(DB_FILE, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                try:
                    cursor = conn.execute("SELECT movies FROM users WHERE username = ?", (username,))
                    result = cursor.fetchone()
                    if result and result[0]:
                        return json.loads(result[0])
                    return []
                finally:
                    conn.close()
        else:
            with engine.connect() as connection:
                result = connection.execute(text("SELECT movies FROM users WHERE username = :user"), {"user": username}).fetchone()
                if result and result[0]:
                    return result[0]
                return []
    except Exception as e:
        print(f"❌ load_ranked_movies 錯誤：{e}")
        return []

def save_ranked_movies(username, movies):
    """儲存使用者的電影列表"""
    try:
        if USE_SQLITE:
            with db_lock:
                conn = sqlite3.connect(DB_FILE, check_same_thread=False)
                try:
                    movies_json = json.dumps(movies, ensure_ascii=False)
                    conn.execute('''
                        INSERT OR REPLACE INTO users (username, movies) 
                        VALUES (?, ?)
                    ''', (username, movies_json))
                    conn.commit()
                    return True
                except Exception as e:
                    print(f"❌ SQLite 儲存失敗：{e}")
                    conn.rollback()
                    return False
                finally:
                    conn.close()
        else:
            movies_json = json.dumps(movies, ensure_ascii=False)
            with engine.connect() as connection:
                connection.execute(text("""
                    INSERT INTO users (username, movies) VALUES (:user, :movies_json)
                    ON CONFLICT (username) DO UPDATE SET movies = :movies_json::jsonb;
                """), {"user": username, "movies_json": movies_json})
                connection.commit()
            return True
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
    return app.send_static_file('index.html')

@app.route('/api/db-info', methods=['GET'])
def get_database_info():
    """顯示資料庫資訊"""
    try:
        if USE_SQLITE:
            with db_lock:
                conn = sqlite3.connect(DB_FILE, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                try:
                    cursor = conn.execute("SELECT COUNT(*) FROM users")
                    user_count = cursor.fetchone()[0]
                    
                    cursor = conn.execute("SELECT username FROM users LIMIT 3")
                    users = [row[0] for row in cursor.fetchall()]
                    
                    return jsonify({
                        'success': True,
                        'provider': 'SQLite (備用模式)',
                        'total_users': user_count,
                        'sample_users': users,
                        'connection_status': 'SQLite Connected',
                        'warning': '⚠️ 資料會在重新部署時遺失！請設定 Neon DATABASE_URL。'
                    })
                finally:
                    conn.close()
        else:
            with engine.connect() as connection:
                user_count = connection.execute(text("SELECT COUNT(*) FROM users")).fetchone()[0]
                version_result = connection.execute(text("SELECT version()")).fetchone()
                
                # 取得使用者樣本
                user_result = connection.execute(text("SELECT username FROM users LIMIT 3")).fetchall()
                users = [row[0] for row in user_result]
                
                # 判斷資料庫提供商
                provider = "PostgreSQL"
                if DATABASE_URL and "neon" in DATABASE_URL.lower():
                    provider = "Neon PostgreSQL"
                elif DATABASE_URL and "supabase" in DATABASE_URL.lower():
                    provider = "Supabase PostgreSQL"
                
                return jsonify({
                    'success': True,
                    'provider': provider,
                    'total_users': user_count,
                    'sample_users': users,
                    'postgresql_version': version_result[0].split(',')[0],
                    'connection_status': 'PostgreSQL Connected',
                    'note': '✅ 使用永久資料庫，資料不會遺失！'
                })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'connection_status': 'Connection failed'
        }), 500

@app.route('/api/register', methods=['POST'])
def register_user():
    try:
        data = request.json
        if not data:
            return jsonify({'error': '無效的請求資料'}), 400
            
        username = data.get('username')
        print(f"🔍 註冊使用者：{username}")
        
        if not is_valid_username(username):
            return jsonify({'error': '無效的使用者名稱，只能使用英文字母和數字。'}), 400
        
        if user_exists(username):
            return jsonify({'error': '此使用者名稱已被註冊。'}), 409
        
        if save_ranked_movies(username, []):
            print(f"✅ 使用者 {username} 註冊成功")
            return jsonify({'success': True, 'username': username})
        else:
            return jsonify({'error': '無法創建使用者，請稍後再試。'}), 500
            
    except Exception as e:
        print(f"❌ 註冊錯誤：{e}")
        return jsonify({'error': '註冊過程發生錯誤'}), 500

@app.route('/api/login', methods=['POST'])
def login_user():
    try:
        data = request.json
        if not data:
            return jsonify({'error': '無效的請求資料'}), 400
            
        username = data.get('username')
        
        if not is_valid_username(username):
            return jsonify({'error': '無效的使用者名稱。'}), 400
        
        if not user_exists(username):
            return jsonify({'error': '使用者不存在。'}), 404
        
        return jsonify({'success': True, 'username': username})
        
    except Exception as e:
        print(f"❌ 登入錯誤：{e}")
        return jsonify({'error': '登入過程發生錯誤'}), 500

def get_username_from_header():
    return request.headers.get('X-Username')

@app.route('/api/movies', methods=['GET', 'DELETE'])
def handle_movies():
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
    title = request.args.get('title')
    if not title:
        return jsonify({'error': 'Title parameter is required'}), 400
        
    results = search_movie_from_tmdb(title)
    if results is None:
        return jsonify({'error': 'Failed to fetch from TMDB'}), 500
        
    return jsonify(results)

@app.route('/api/random', methods=['GET'])
def get_random_movie():
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
    init_db()
    app.run(port=5000)
else:
    print("🚀 電影排名系統在 Render 上啟動...")
    init_db()
