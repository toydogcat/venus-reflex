import os
import shutil
import time

SRC_DIR = '/home/toby/documents/projects/venus-reflex/bank'
BASE_DIR = '闇河魅影（web）'
DST_ARCHIVE = '/home/toby/documents/ftp_folder/闇河魅影（web）'

def main():
    print(f"Compressing folder {os.path.join(SRC_DIR, BASE_DIR)} into zip...")
    t0 = time.time()
    
    # shutil.make_archive will append '.zip' to base_name
    archive_path = shutil.make_archive(
        base_name=DST_ARCHIVE,
        format='zip',
        root_dir=SRC_DIR,
        base_dir=BASE_DIR
    )
    
    t1 = time.time()
    file_size_mb = os.path.getsize(archive_path) / (1024 * 1024)
    print(f"\nCompression complete!")
    print(f"Archive saved to: {archive_path}")
    print(f"Archive Size: {file_size_mb:.2f} MB")
    print(f"Time Taken: {t1 - t0:.2f} seconds")

if __name__ == '__main__':
    main()
