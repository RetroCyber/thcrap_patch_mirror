# 镜像站用同步脚本
# 功能：
# 1.读取仓库（repo）版本信息，与源服务器做对比
# 2.比较源服务器与 repo 文件列表的差异
# 3.自动下载或清理变动文件
# 4.自动更新版本信息
# 5.逐个补丁（patch）更新，并能够实时更新版本信息
# 6.输出脚本日志信息
import httpx
import json
import asyncio
import os
import sys
import argparse
from repo_update import repo_build
from color_logger import ColorLogger
from urllib.parse import urljoin
from hashlib import sha256
from enum import Enum
from zlib import crc32

log = ColorLogger(log_to_file=True).logger
parser = argparse.ArgumentParser()
parser.add_argument(
    "-m","--mirror",
    metavar="path",
    help="The path to be mirrored",
    default='.',
    type=str,
    dest='m'
    )
class UpdateInfo(Enum):
    checksum = 0
    upd_mode = 1 


# 获取 patch 文件更新列表以及更新模式
class UpdateMode(Enum):
    REMOVE = "r"
    UPDATE = "u"

# 对 URL 进行格式化
def format_url(url):
    if not url.endswith('/'):
        return url + '/'
    return url

# 获取文件 CRC32 校验和
def calculate_crc32(file_path):
    try:
        with open(file_path, 'rb') as f:
            checksum = 0
            while chunk := f.read(4096):  # 分块读取文件
                checksum = crc32(chunk, checksum)
            # 返回CRC32值，转换为无符号整数
            return checksum & 0xFFFFFFFF
    except FileNotFoundError:
        log.error("File not found.")
        return None
    except Exception as e:
        log.error(f"An error occurred: {e}")
        return None

# 获取用户镜像站路径
def load_custom_dir(user_arg):

    # 获取脚本所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    mirror_file_path = os.path.join(current_dir, 'mirror.json')
    config_file_path = os.path.join(current_dir, 'config.json')

    # 检查 mirror.json 文件
    if os.path.exists(mirror_file_path):
        with open(mirror_file_path, 'r+') as f:
            data = json.load(f)
            # 验证 JSON 结构
            if 'mirror_dir' not in data or not data['mirror_dir']:
                data['mirror_dir'] = current_dir
                f.seek(0)
                json.dump(data, f, indent=4)
                f.truncate()
        return data['mirror_dir']

    # 检查 config.json 文件
    elif os.path.exists(config_file_path):
        with open(config_file_path, 'r') as f:
            data = json.load(f)
            if 'mirror_dir' in data and data['mirror_dir']:
                with open(mirror_file_path, 'w') as mirror_file:
                    json.dump({'mirror_dir': data['mirror_dir']}, mirror_file, indent=4)
                return data['mirror_dir']

    # 如果两个文件都不存在，从参数获取路径
    else:
        user_path = {}
        # 格式化路径，确保以斜杠结尾
        if user_arg == '.':
            log.info("No path is specified, using the current path.")
        user_path['mirror_dir'] = os.path.join(os.path.abspath(user_arg.strip()), '')
        with open(mirror_file_path, 'w') as mirror_file:
            json.dump(user_path, mirror_file, indent=4)
        return user_path['mirror_dir']

# 获取镜像 patch 版本数据
async def fetch_patch_ver(patch_ver):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(patch_ver)
            response.raise_for_status()  # 如果请求失败则抛出异常
            return sha256(response.content).hexdigest()
        except Exception as e:
            log.error(f"Error accessing {patch_ver}: {e}")
            sys.exit(1)

# 检查 repo 更新
async def check_update(mirror_dir):
    update_list = {}
    version_dir = os.path.join(mirror_dir, '.version')
    if not os.path.exists(version_dir):
        log.error(f"{version_dir} does not exist.")
        sys.exit(1)

    for repo_id in os.listdir(version_dir):
        if not repo_id.endswith('.json'):
            continue

        repo_id = repo_id[:-5]  # Remove .json extension
        file_path = os.path.join(version_dir, f"{repo_id}.json")

        try:
            log.info(f"Checking {repo_id} ...")
            with open(file_path, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError:
            log.error(f"Invalid JSON in {repo_id}. Skipping.")
            continue

        origin = data.get('origin')
        patches = data.get('patches', {})

        if not origin or not isinstance(patches, dict):
            log.error(f"Invalid data format in {repo_id}. Skipping.")
            continue

        for patch, current_hash in patches.items():
            patch_url = urljoin(format_url(origin), patch)
            patch_file_js_url = f"{patch_url}/files.js?=2233"

            new_hash = await fetch_patch_ver(patch_file_js_url)

            if new_hash is None:
                log.error(f"Failed to fetch the hash {patch_file_js_url}.")
                continue

            if current_hash != new_hash:
                if repo_id not in update_list:
                    update_list[repo_id] = []
                update_list[repo_id].append([patch, patch_url, new_hash])
                log.info(f"{patch} have a new version!")
        log.info("Check finished.")

    return update_list

async def fetch_update_list(patch_dir, patch_url):
    update_list = {}

    async with httpx.AsyncClient() as client:
        # Step 1: Construct patch_dir and read local files.js
        local_files_path = os.path.join(patch_dir, "files.js")

        if not os.path.exists(local_files_path):
            log.warning(f"{local_files_path} does not exist.")
            return update_list

        with open(local_files_path, "r") as f:
            local_filelist = json.load(f)

        local_filelist.pop("patch.js", None)

        # Step 2: Fetch origin files.js from the server
        patch_filelist_url = f"{format_url(patch_url)}files.js?=2233"

        try:
            response = await client.get(patch_filelist_url)
            response.raise_for_status()
            origin_filelist = response.json()
        except httpx.RequestError as e:
            log.error(f"An error occurred while requesting {e.request.url!r}.")
            return update_list
        except httpx.HTTPStatusError as e:
            log.error(f"Error response {e.response.status_code} while requesting {e.request.url!r}.")
            return update_list

        origin_filelist.pop("patch.js", None)

        # Step 3: Compare the local and origin file lists
        for pfn, local_hash in local_filelist.items():
            origin_hash = origin_filelist.get(pfn)
            if local_hash is not None and origin_hash is None:
                # update_list[pfn] = UpdateMode.REMOVE
                update_list[pfn] = [local_hash, UpdateMode.REMOVE.value]
            elif origin_hash is not None and local_hash != origin_hash:
                # update_list[pfn] = UpdateMode.UPDATE
                update_list[pfn] = [origin_hash, UpdateMode.UPDATE.value]
        for pfn, origin_hash in origin_filelist.items():
            if pfn not in local_filelist and origin_hash is not None:
                # update_list[pfn] = UpdateMode.UPDATE
                update_list[pfn] = [origin_hash, UpdateMode.UPDATE.value]

    return update_list

# 保存当前更新列表，防止脚本意外中断
def save_update_list(mirror_dir, repo_id, patch, patch_dir, patch_url, new_hash, update_list):
    # 构建需要写入的temp_update_info数据结构
    temp_update_info = {
        "repo_id": repo_id,
        "patch": patch,
        "patch_dir": patch_dir,
        "patch_url": patch_url,
        "new_hash": new_hash,
        "files": {pfn: [info[UpdateInfo.checksum.value], info[UpdateInfo.upd_mode.value]] for pfn, info in update_list.items()}
    }
    
    # 定义文件路径
    update_file_path = os.path.join(mirror_dir, '__update.json')
    
    # 将temp_update_info写入到__update.json中，若文件已存在则覆盖
    with open(update_file_path, 'w', encoding='utf-8') as f:
        json.dump(temp_update_info, f, ensure_ascii=False, indent=4)

# 载入上次意外中断的更新信息
def load_last_info(mirror_dir):
    update_file_path = os.path.join(mirror_dir, "__update.json")
    
    # Check if the __update.json file exists
    if not os.path.exists(update_file_path):
        return None
    
    # Load the update info from the JSON file
    with open(update_file_path, "r") as update_file:
        update_info = json.load(update_file)
    
    repo_id = update_info.get("repo_id", "")
    patch = update_info.get("patch", "")
    patch_dir = update_info.get("patch_dir", "")
    patch_url = update_info.get("patch_url", "")
    new_hash = update_info.get("new_hash", "")
    files_info = update_info.get("files", {})
    
    update_list = {}
    
    for pfn, (checksum, upd_mode) in files_info.items():
        file_path = os.path.join(patch_dir, pfn)
        
        # Check if the file exists
        if not os.path.exists(file_path):
            continue
        
        # Calculate the CRC32 checksum of the file
        file_checksum = calculate_crc32(file_path)
        
        # If checksum matches, skip this file
        if file_checksum == checksum:
            continue
        
        # Otherwise, add it to the update list
        update_list[pfn] = [checksum, upd_mode]
    
    # Return the results
    return repo_id, patch, patch_dir, patch_url, new_hash, update_list

# 完成上次更新
async def finish_last_update(mirror_dir):
    # 载入中断状态
    repo_id, patch, patch_dir, patch_url, new_hash, lupd = load_last_info(mirror_dir)
    if lupd:
        await process_update(patch_dir, patch_url, lupd)
        remove_old_filelist(patch_dir)
        update_version_info(mirror_dir, repo_id, patch, new_hash)
        repo_dir = os.path.join(mirror_dir, repo_id)
        repo_build(repo_dir, repo_dir)

# 更新 patch 文件
async def fetch_update(patch_url, pfn, patch_dir, file_semaphore, rate_limit_kbps=1024, max_retries=5):
    rate_limit_bps = rate_limit_kbps * 1024
    retry_count = 0
    success = False
    while retry_count < max_retries and not success:
        try:
            async with file_semaphore:
                file_url = urljoin(format_url(patch_url), f"{pfn}?=2233") # 合成文件的完整URL
                file_path = os.path.normpath(os.path.join(patch_dir, pfn))  # 合成文件保存路径
                os.makedirs(os.path.dirname(file_path), exist_ok=True)  # 创建目录
                file_name = os.path.basename(file_path)
                file_dir = os.path.dirname(file_path)
                temp_file_path = os.path.join(file_dir, f"{file_name}.downloading")
                
                async with httpx.AsyncClient() as client:

                    async with client.stream("GET", file_url) as response:
                        response.raise_for_status()
                        with open(temp_file_path, "wb") as temp_file:
                            async for chunk in response.aiter_bytes():
                                temp_file.write(chunk)

                                # Calculate sleep time to enforce rate limit
                                time_to_sleep = len(chunk) / rate_limit_bps
                                await asyncio.sleep(time_to_sleep)

                # 如果目标文件已存在，先删除
                if os.path.exists(file_path):
                    os.remove(file_path)

                # 重命名文件为最终名称
                os.rename(temp_file_path, file_path)
                log.update(file_path)
                success = True
        
        except (httpx.HTTPStatusError, httpx.RequestError, OSError) as e:
            retry_count += 1
            log.info(f"Error downloading: {file_path}    Retry {retry_count}/{max_retries}")
            if retry_count >= max_retries:
                log.error(f"Failed to download {file_path} after {max_retries} retries.")

# 清理过时的 patch 文件
def clean_patch(patch_dir, pfn):
    # 合成补丁文件路径
    pf_dir = os.path.join(patch_dir, pfn)
    
    # 删除补丁文件
    if os.path.isfile(pf_dir):
        os.remove(pf_dir)
        log.remove(f"{pf_dir}")
    else:
        log.error(f"File not found: {pf_dir}")
        return
    
    # 删除空文件夹，直到文件夹不为空
    current_dir = os.path.dirname(pf_dir)
    while current_dir != patch_dir:
        try:
            os.rmdir(current_dir)
            current_dir = os.path.dirname(current_dir)
        except OSError:
            break

# 处理 patch 文件更新
async def process_update(patch_dir, patch_url, update_list):
    ld = []
    lr = []

    # 遍历update_list，将键放入对应的列表
    for pfn, upd_info in update_list.items():
        if upd_info[UpdateInfo.checksum.value] == UpdateMode.UPDATE.value:
            ld.append(pfn)
        elif upd_info[UpdateInfo.upd_mode.value] == UpdateMode.REMOVE.value:
            lr.append(pfn)

    # 创建一个信号量，限制最大并发数为5
    file_semaphore = asyncio.Semaphore(5)

    # 异步获取更新
    tasks = [fetch_update(patch_url, pfn, patch_dir, file_semaphore) for pfn in ld]
    await asyncio.gather(*tasks)

    # 清理补丁
    for pfn in lr:
        clean_patch(patch_dir, pfn)
    log.succ("Finished clean!")

# 删除原有文件列表(files.js)
def remove_old_filelist(patch_dir):
    # 构建files.js文件的完整路径
    files_js_path = os.path.join(patch_dir, 'files.js')
    
    # 删除files.js文件，如果存在的话
    if os.path.exists(files_js_path):
        os.remove(files_js_path)
        log.info(f"Deleted {files_js_path}")
    else:
        log.info(f"{files_js_path} does not exist, no need to delete.")

# 更新 patch 版本信息
def update_version_info(mirror_dir, repo_id, patch, new_hash):
    # 构建文件路径
    file_path = os.path.join(mirror_dir, '.version', f'{repo_id}.json')
    
    # 读取JSON文件内容
    try:
        with open(file_path, 'r', encoding='utf-8') as json_file:
            data = json.load(json_file)
    except FileNotFoundError:
        log.error(f"The file {file_path} was not found.")
        return
    except json.JSONDecodeError:
        log.error(f"The file {file_path} is not a valid JSON.")
        return
    
    # 更新 patch 版本信息
    if 'patches' in data and patch in data['patches']:
        data['patches'][patch] = new_hash
    else:
        log.error(f"Patch '{patch}' not found in the file.")
        return
    
    # 将更新后的数据结构写回文件
    try:
        with open(file_path, 'w', encoding='utf-8') as json_file:
            json.dump(data, json_file, indent=4, ensure_ascii=False)
        log.succ(f"{repo_id}:Patch version updated!")
    except IOError:
        log.error(f"Could not write to file {file_path}.")


async def main():

    # 载入用户设置的镜像站路径
    args = parser.parse_args()
    mirror_dir = load_custom_dir(args.m)

    # 若上次更新发生中断则优先完成
    update_path = os.path.join(mirror_dir, "__update.json")
    log.info("Checking if last update interrupt...")
    if os.path.exists(update_path):
        log.info("Exception interrupt detected! Recovering...")
        await finish_last_update(mirror_dir)
    else:
        log.info("Check finished.")

    # 检查 patch 更新
    check_list = await check_update(mirror_dir)

    if check_list:
            # 遍历欲更新 patch 列表
        for repo_id, patch_info in check_list.items():
            # 遍历 repo 内所包含的 patch 信息
            for patch, patch_url, new_hash in patch_info:
                patch_dir = os.path.join(mirror_dir, repo_id, patch)
                lupd = await fetch_update_list(patch_dir, patch_url)

                # 进行 patch 文件更新
                if lupd:
                    save_update_list(mirror_dir, repo_id, patch, patch_dir, patch_url, new_hash, lupd)
                    await process_update(patch_dir, patch_url, lupd)
                    remove_old_filelist(patch_dir)
                    update_version_info(mirror_dir, repo_id, patch, new_hash)
            
            # 在当前 repo_id 的所有元素处理完之后调用 repo_build()
            repo_dir = os.path.join(mirror_dir, repo_id)
            repo_build(repo_dir, repo_dir)

        # 删除更新状态文件
        if os.path.exists(update_path):
            os.remove(update_path)

asyncio.run(main())