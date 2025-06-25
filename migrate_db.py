#!/usr/bin/env python3
"""
Database Optimization Script for Chess Trap Trainer
Run this script to optimize your chess_traps.db database for better performance.
"""

import sqlite3
import os
import time
import sys

def check_database_exists(db_path):
    """Check if database file exists."""
    if not os.path.exists(db_path):
        print(f"❌ ERROR: Database file '{db_path}' not found!")
        print(f"   Current directory: {os.getcwd()}")
        return False
    
    # Check file size
    size_mb = os.path.getsize(db_path) / (1024 * 1024)
    print(f"✓ Found database: {db_path} ({size_mb:.2f} MB)")
    return True

def get_database_stats(conn):
    """Get statistics about the database."""
    stats = {}
    
    # Total traps
    cursor = conn.execute("SELECT COUNT(*) FROM traps")
    stats['total_traps'] = cursor.fetchone()[0]
    
    # Database page count and size
    cursor = conn.execute("PRAGMA page_count")
    stats['page_count'] = cursor.fetchone()[0]
    
    cursor = conn.execute("PRAGMA page_size")
    stats['page_size'] = cursor.fetchone()[0]
    
    # Calculate size
    stats['size_mb'] = (stats['page_count'] * stats['page_size']) / (1024 * 1024)
    
    # Check for index
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_moves_hash'")
    stats['has_index'] = cursor.fetchone() is not None
    
    return stats

def optimize_database_once(db_path="chess_traps.db"):
    """Run once to optimize database structure."""
    print("\n" + "="*60)
    print("CHESS TRAP DATABASE OPTIMIZER")
    print("="*60 + "\n")
    
    if not check_database_exists(db_path):
        return False
    
    try:
        # Get initial stats
        print("📊 Analyzing database before optimization...")
        with sqlite3.connect(db_path) as conn:
            before_stats = get_database_stats(conn)
            print(f"   - Total traps: {before_stats['total_traps']:,}")
            print(f"   - Database size: {before_stats['size_mb']:.2f} MB")
            print(f"   - Has index: {'Yes' if before_stats['has_index'] else 'No'}")
        
        # Start optimization
        print("\n🔧 Starting optimization process...")
        start_time = time.time()
        
        with sqlite3.connect(db_path) as conn:
            # 1. ANALYZE - Update statistics
            print("   1/4 Updating database statistics...")
            conn.execute("ANALYZE")
            
            # 2. Create index if missing
            if not before_stats['has_index']:
                print("   2/4 Creating missing index...")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_moves_hash ON traps(moves_hash)")
            else:
                print("   2/4 Index already exists ✓")
            
            # 3. Optimize storage
            print("   3/4 Optimizing database storage...")
            conn.execute("PRAGMA optimize")
            
            conn.commit()
        
        # 4. VACUUM - This needs to be done separately
        print("   4/4 Vacuuming database (this may take a while)...")
        vacuum_conn = sqlite3.connect(db_path)
        vacuum_conn.execute("VACUUM")
        vacuum_conn.close()
        
        # Get final stats
        print("\n📊 Analyzing database after optimization...")
        with sqlite3.connect(db_path) as conn:
            after_stats = get_database_stats(conn)
            print(f"   - Total traps: {after_stats['total_traps']:,}")
            print(f"   - Database size: {after_stats['size_mb']:.2f} MB")
            print(f"   - Size reduction: {before_stats['size_mb'] - after_stats['size_mb']:.2f} MB")
        
        elapsed = time.time() - start_time
        print(f"\n✅ Optimization completed in {elapsed:.2f} seconds!")
        
        # Additional recommendations
        print("\n💡 Recommendations for better performance:")
        print("   - Place database on SSD drive")
        print("   - Keep at least 4GB RAM free during imports")
        print("   - Close other applications during large imports")
        
        return True
        
    except sqlite3.Error as e:
        print(f"\n❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function."""
    # Check command line arguments
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = "chess_traps.db"
    
    print(f"Using database: {db_path}")
    
    # Ask for confirmation
    response = input("\nDo you want to optimize this database? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Optimization cancelled.")
        return
    
    # Run optimization
    success = optimize_database_once(db_path)
    
    if success:
        print("\n🎉 Database optimization successful!")
    else:
        print("\n❌ Database optimization failed!")
    
    # Wait before closing
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()