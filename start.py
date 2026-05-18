#!/usr/bin/env python3
"""
BidMaster Pro 快速启动脚本
用于检查环境依赖并启动服务
"""

import os
import sys
import subprocess
import importlib.util
from pathlib import Path

def check_python_version():
    """检查 Python 版本"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print(f"❌ Python 版本过低: {version.major}.{version.minor}")
        print("   需要 Python 3.11+")
        return False
    print(f"✅ Python 版本: {version.major}.{version.minor}.{version.micro}")
    return True

def check_postgres():
    """检查 PostgreSQL 是否运行"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            user="postgres",
            password="postgres",
            database="postgres"
        )
        conn.close()
        print("✅ PostgreSQL 连接成功")
        return True
    except Exception as e:
        print(f"⚠️ PostgreSQL 连接失败: {e}")
        print("   请确保 PostgreSQL 已启动且配置正确")
        return False

def check_redis():
    """检查 Redis 是否运行"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379)
        r.ping()
        print("✅ Redis 连接成功")
        return True
    except Exception as e:
        print(f"⚠️ Redis 连接失败: {e}")
        print("   请确保 Redis 已启动")
        return False

def check_env_file():
    """检查 .env 文件"""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        print("⚠️ .env 文件不存在")
        print("   正在从 .env.example 创建...")
        example_path = Path(__file__).parent / ".env.example"
        if example_path.exists():
            import shutil
            shutil.copy(example_path, env_path)
            print("✅ 已创建 .env 文件，请填写 API Key")
        else:
            print("❌ .env.example 也不存在")
        return False
    print("✅ .env 文件存在")
    return True

def check_dependencies():
    """检查关键依赖"""
    required = [
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("sqlalchemy", "SQLAlchemy"),
        ("pydantic", "Pydantic"),
        ("litellm", "LiteLLM"),
    ]
    
    missing = []
    for module, name in required:
        if importlib.util.find_spec(module) is None:
            missing.append(name)
            print(f"❌ 缺少依赖: {name}")
        else:
            print(f"✅ 依赖已安装: {name}")
    
    return len(missing) == 0

def install_dependencies():
    """安装依赖"""
    print("\n📦 正在安装依赖...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", "."],
        cwd=Path(__file__).parent
    )
    return result.returncode == 0

def create_database():
    """创建数据库"""
    print("\n🗄️ 检查数据库...")
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            user="postgres",
            password="postgres",
            database="postgres"
        )
        conn.autocommit = True
        cur = conn.cursor()
        
        # 检查数据库是否存在
        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'bidmaster'")
        if not cur.fetchone():
            print("   正在创建数据库 bidmaster...")
            cur.execute("CREATE DATABASE bidmaster")
            print("✅ 数据库 bidmaster 创建成功")
        else:
            print("✅ 数据库 bidmaster 已存在")
        
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ 数据库操作失败: {e}")
        return False

def start_server():
    """启动服务器"""
    print("\n🚀 启动 FastAPI 服务...")
    print("=" * 50)
    print("访问地址: http://localhost:8000")
    print("API 文档: http://localhost:8000/docs")
    print("=" * 50)
    print("\n按 Ctrl+C 停止服务\n")
    
    os.chdir(Path(__file__).parent)
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "services.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--reload"
    ])

def main():
    print("=" * 50)
    print("  BidMaster Pro 启动检查")
    print("=" * 50)
    print()
    
    # 检查 Python 版本
    if not check_python_version():
        sys.exit(1)
    
    print()
    
    # 检查 .env 文件
    check_env_file()
    
    print()
    
    # 检查依赖
    if not check_dependencies():
        print("\n是否安装缺失的依赖? (y/n): ", end="")
        if input().lower() == 'y':
            if not install_dependencies():
                print("❌ 依赖安装失败")
                sys.exit(1)
        else:
            sys.exit(1)
    
    print()
    
    # 检查数据库
    if check_postgres():
        create_database()
    
    print()
    
    # 检查 Redis
    check_redis()
    
    print()
    print("=" * 50)
    print("  环境检查完成")
    print("=" * 50)
    
    # 启动服务
    start_server()

if __name__ == "__main__":
    main()
