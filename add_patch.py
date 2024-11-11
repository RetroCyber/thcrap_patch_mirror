# 镜像站用添加补丁脚本
# 功能：
# 1.可直接输入仓库(repo)或补丁(patch)的 URL 进行添加
# 2.给定仓库(repo)URL，列举其下所有补丁(patch)，选择添加
# 3.引导用户生成自定义配置文件，可供镜像脚本(mirror_patch.py)使用
# 4.自动调用 repo_update.py 构建补丁，允许thcrap直接下载使用
import httpx
import json
import asyncio
import aiofiles
import os
import re
import sys
import time
from repo_update import repo_build, enter_missing
from color_logger import ColorLogger
from urllib.parse import urljoin, urlparse
from hashlib import sha256
from zlib import crc32
from dataclasses import dataclass

log = ColorLogger().logger

@dataclass(frozen=True)
class ADD_MODE:
    ADD_REPO: int = 1
    ADD_PATCH: int = 2

add_mode = ADD_MODE()

# 载入用户配置
def load_config():
    config = None
    # 获取脚本所在目录
    log.info("Loading custom config...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.json')
    if os.path.exists(config_path):
        try:
            with open("config.json","r") as f:
                config = json.load(f)

            # 检查配置合法性
            required_keys = ['site_url', 'mirror_dir', 'thpatch']
            for key in required_keys:
                if key not in config:
                    raise ValueError(f"Missing required key: {key}")
                if config[key] in [None, '', []]:
                    raise ValueError(f"Value for key '{key}' is empty or None")
            
            log.succ("Config file is valid.")

        except json.JSONDecodeError:
            log.error("Config file is not a valid JSON.")
        except ValueError as ve:
            log.error(f"Config validation error: {ve}")
        
    else:
        log.info("Missing configuration file, generating...")
        config = custom_config()
    return config

# 生成用户配置
def custom_config():
    config = {}
    enter_missing(config, 'site_url', "Enter the public URL of your site(End with '/'):")
    enter_missing(config, 'mirror_dir', "Where to store patches:")
    enter_missing(config, 'thpatch', "Which folder stores mirrored thpatch's patches(important):")

    with open("config.json",'w') as f:
        json.dump(config, f, indent=4)
    
    return config

# 对 URL 进行格式化
def format_url(url: str):
    if not url.endswith('/'):
        return url + '/'
    return url

# 获取 URL 最后一级
def get_last_path_segment(url: str):
    parsed_url = urlparse(url)
    path = parsed_url.path

    # Remove trailing slash if it exists
    if path.endswith('/'):
        path = path[:-1]

    # Split the path by '/' and get the last segment
    last_segment = path.split('/')[-1]
    return last_segment

# 获取文件 CRC32 校验和
async def calculate_crc32(file_path: str):
    try:
        async with aiofiles.open(file_path, 'rb') as f:
            checksum = 0
            while True:
                chunk = await f.read(4096)  # 异步分块读取文件
                if not chunk:
                    break
                checksum = crc32(chunk, checksum)
        # 返回CRC32值，转换为无符号整数
        return checksum & 0xFFFFFFFF
    except FileNotFoundError:
        log.error("File not found.")
        return None
    except Exception as e:
        log.error(f"An error occurred: {e}")
        return None

# 校验已下载的文件是否完整
async def check_file(pfn: str, checksum: int, dp_dir: str):
    pf_path = os.path.join(dp_dir, pfn)
    if os.path.exists(pf_path):
        file_checksum = await calculate_crc32(pf_path)
        if file_checksum == checksum:
            return True
    return False

# 获取 patch 文件列表信息
async def fetch_patch_file_info(patch_url: str):

    # 合成 files.js 的完整 URL
    files_js_url = urljoin(format_url(patch_url), "files.js?=2233")

    # 获取 JSON 数据
    async with httpx.AsyncClient() as client:
        response = await client.get(files_js_url)
        response.raise_for_status()
        json_data = response.json()

        # 获取 patch 文件信息键值对，舍弃空值项（远端文件已删除）
        file_info = {key: value for key, value in json_data.items() if value is not None}
        return file_info

# 获取 repo 信息（repo.js 内容）
async def fetch_repo_info(url: str, am=add_mode.ADD_REPO):
    async with httpx.AsyncClient() as client:
        try:
            if am == add_mode.ADD_REPO:
                # Mode 1: Directly append 'repo.js' to the repo URL
                repo_js_url = urljoin(url, 'repo.js')
            elif am == add_mode.ADD_PATCH:
                # Mode 2: Assume the URL is for a patch, go one level up to get 'repo.js'
                repo_js_url = urljoin(url, '../repo.js')
            else:
                raise ValueError("Invalid mode. Mode should be 1 for repo or 2 for patch.")
            
            # Fetch the repo.js content
            response = await client.get(repo_js_url)
            response.raise_for_status()  # Raise an error for bad responses

            # Parse the JSON content
            repo_info = response.json()
            return repo_info

        except httpx.HTTPStatusError as e:
            log.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
            sys.exit(1)
        except json.JSONDecodeError:
            log.error("Failed to decode JSON from the response.")
            sys.exit(1)
        except Exception as e:
            log.error(f"An error occurred: {str(e)}")
            sys.exit(1)

# 生成镜像 patch 版本数据
async def fetch_patch_ver(patch_ver: str):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(patch_ver)
            response.raise_for_status()  # 如果请求失败则抛出异常
            return sha256(response.content).hexdigest()
        except Exception as e:
            log.error(f"Error accessing {patch_ver}: {e}")
            sys.exit(1)

# 生成镜像站用 repo.js
def generate_repo_js(repo_js, repo_dir: str, servers: str):
    if repo_js.get('id') == 'thpatch':
        repo_build(repo_dir,repo_dir)
    else:
        repo_js['servers'] = [servers]
        repo_js_path = os.path.join(repo_dir,"repo.js")
        try:
            with open(repo_js_path,'w',encoding='utf-8') as f:
                json.dump(repo_js,f,ensure_ascii=False,indent=4)
        except IOError:
            log.error(f"Error writing to file {repo_js_path}.")
            return
        repo_build(repo_dir,repo_dir)

# 下载 patch 文件
async def download_patch(base_url: str, pfn: str, patch_dir: str, file_semaphore, rate_limit_kbps=1024, max_retries=5):
    rate_limit_bps = rate_limit_kbps * 1024
    retry_count = 0
    success = False
    while retry_count < max_retries and not success:
        try:
            async with file_semaphore:
                file_url = urljoin(format_url(base_url), f"{pfn}?=2233") # 合成文件的完整URL
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
                log.get(file_path)
                success = True
        
        except (httpx.HTTPStatusError, httpx.RequestError, OSError) as e:
            retry_count += 1
            log.info(f"Error downloading: {file_path}    Retry {retry_count}/{max_retries}")
            if retry_count >= max_retries:
                log.error(f"Failed to download {file_path} after {max_retries} retries.")

# 从远端 repo 镜像指定 patch
async def mirror_patch_from_repo(base_url: str, repo_dir: str, repo_id: str, ipatch=""):

    # 获取 patch 文件列表
    patch_url = urljoin(format_url(base_url), ipatch)
    pn = get_last_path_segment(patch_url)
    log.info(f"Mirroring {pn} ...")
    file_info = await fetch_patch_file_info(patch_url)
    flist = list(file_info.keys())
    mirror_dir = os.path.dirname(repo_dir)

# 将ldpf数据转换为JSON数据并写入__files.js文件
    ldpf_path = os.path.join(mirror_dir, "__files.js")
    with open(ldpf_path, 'w', encoding='utf-8') as ldpf_file:
        json.dump(file_info, ldpf_file, ensure_ascii=False, indent=4)

    # 生成补丁路径
    patch_dir = os.path.join(repo_dir, pn)

    # 设置最大并发数
    semaphore = asyncio.Semaphore(10)
    tasks = [download_patch(patch_url, pfn, patch_dir, semaphore) for pfn in flist]
    await asyncio.gather(*tasks)

    # 生成 patch 版本文件
    repo_url = urljoin(format_url(patch_url),'..')
    await generate_mirror_info(mirror_dir, repo_url, repo_id, pn)

# 生成镜像 repo 版本信息
async def generate_mirror_info(mirror_dir: str, repo_origin: str, repo_id: str, patch: str):

    # 创建 JSON 文件的路径
    json_file_path = os.path.join(mirror_dir, ".version", f"{repo_id}.json")
    os.makedirs(os.path.dirname(json_file_path), exist_ok=True)

    # 生成 patch_ver URL
    patch_ver = urljoin(format_url(repo_origin), f"{patch}/files.js?=2233")

    # 使用异步方式访问 URL 并计算 SHA256 值
    hash_ver = await fetch_patch_ver(patch_ver)
    if hash_ver == None:
        return

    # 检查文件是否存在以及是否需要更新
    if os.path.exists(json_file_path):
        # 读取现有文件内容
        with open(json_file_path, 'r') as f:
            existing_data = json.load(f)
        try:
            if isinstance(existing_data, dict) and 'origin' in existing_data and 'patches' in existing_data:
                # 更新 patches
                existing_data["patches"][patch] = hash_ver
                with open(json_file_path, 'w') as f:
                    json.dump(existing_data, f, indent=4)
                return
        except json.JSONDecodeError:
            pass    # 文件内容不符合要求，继续到清空并重写

    # 如果文件内容不符合要求，写入完整的 data 结构
    data = {
            "origin": repo_origin,
            "patches": {patch: hash_ver}
        }
    with open(json_file_path, 'w') as f:
        json.dump(data, f, indent=4)

# 判断 URL 指向为 repo 还是 patch
def IsRepoOrServer(url: str):
    try:
            # 创建一个 HTTP 客户端 
            with httpx.Client() as client:

                # 检查基本 URL 是否可访问
                response = client.get(url,timeout=10)
                if response.status_code == 200:
                    log.succ(f"{url} is accessible.")
                else:
                    log.error(f"{url} is not accessible. Status code: {response.status_code}")
                    sys.exit(1)

                # 检查 base_url + repo.js 是否可访问
                repo_js_url = url.rstrip('/') + '/repo.js'
                response = client.get(repo_js_url, timeout=10)
                if response.status_code == 200:
                    log.succ("Find repo.js. This Repo contains:")
                    print("- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -")
                    return add_mode.ADD_REPO
                else:

                    # 检查 base_url + files.js 是否可访问
                    files_js_url = url.rstrip('/') + '/files.js'
                    response = client.get(files_js_url, timeout=10)
                    if response.status_code == 200:
                        log.succ("Find files.js. Downloading...")
                        return add_mode.ADD_PATCH
                    else:
                        raise ValueError("Invalid URL, please check it to make sure is correct.")
    except httpx.RequestError as exc:
        log.error(f"An error occurred while requesting {url}: {exc}")
        sys.exit(1)
    except ValueError as e:
        log.error(f"{str(e)}")
        sys.exit(1)

# 枚举 repo 包含的 patch ，并返回 patch 列表
def enumerate_patch(url: str):
    """
    从指定URL获取JSON数据并解析，输出其中所包含的补丁(patch)，并返回补丁列表
    """
    # 得到repo.js的URL
    repo_js_url = url.rstrip('/') + '/repo.js'

    # 从URL获取JSON数据
    response = httpx.get(repo_js_url)
    response.raise_for_status()  # 收集错误访问代码

    # 解析JSON数据
    parsed_data = response.json()

    # 获取patch列表
    patches = parsed_data.get("patches", {})

    # 格式化输出patch列表
    for i, (patch, description) in enumerate(patches.items(), start=1):
        print(f"{i}: {patch} - {description}")
    print("- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -")
    return list(patches.keys())

# 将不需要定期镜像的 patch 从镜像列表删除，以减少镜像开销。
def delete_mirror_item(mirror_dir: str, repo_id: str, patch: str):
    # 构造出 version_dir 路径
    version_dir = os.path.join(mirror_dir, '.version')
    
    # 构造出 repo_id.json 的完整路径
    fv_path = os.path.join(version_dir, f'{repo_id}.json')
    
    # 检查 repo_id.json 文件是否存在
    if os.path.exists(fv_path):
        with open(fv_path, 'r') as file:
            data = json.load(file)
        
        # 检查并删除 patches 中的对应项
        if 'patches' in data and patch in data['patches']:
            del data['patches'][patch]
        
        # 如果 patches 为空，则删除整个 repo_id.json 文件
        if not data.get('patches'):
            os.remove(fv_path)
        else:
            # 如果有其它内容，写回文件
            with open(fv_path, 'w') as file:
                json.dump(data, file, indent=4)
    
    # 检查 .version 文件夹是否为空
    if os.path.isdir(version_dir) and not os.listdir(version_dir):
        os.rmdir(version_dir)

def remove_mirror_list(mirror_dir: str, repo_id: str, patch_data: list):
    print("Which patches are one-time (no updates required):")
    print("- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -")
    for i, patch in enumerate(patch_data, start=1):
        print(f"{i}. {patch}")
    print("- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -")
    user_input = input(f"Select the appropriate patch numbers(1-{len(patch_data)}) separated by commas and/or spaces, or leave input blank to skip all options shown (Enter 'a' for all):")
    user_options_list = re.split(r'[,\s]+',user_input.strip())
    if user_options_list[0] != '' and user_options_list[0] != 'a':
        try:
            for i in user_options_list:
                i = int(i)
                if i>=1 and i <= len(user_options_list):
                    delete_mirror_item(mirror_dir, repo_id, patch_data[i])
                else:
                    raise ValueError(f"Invalid option: {i}, skipping.")
        except ValueError as v:
            log.error(f"{str(v)}")
            pass
        except Exception as e:
            log.error(f"An Error Occurred: {str(e)}")
            sys.exit(1)
    elif user_options_list[0] == 'a':
        for i in patch_data:
            delete_mirror_item(mirror_dir, repo_id, i)

# 将新添加 patch 加入镜像站索引
def build_index(thpatch_dir: str, repo_id: str, mirror_repo_url: str):
    log.info(f"Adding index for {repo_id}...")
    # 构建repo.js文件的路径
    repo_path = os.path.join(thpatch_dir, 'repo.js')
    
    # 检查repo.js文件是否存在
    if not os.path.exists(repo_path):
        log.warning("The main server(thpatch repo) has not been established, skipping.")
        return
    
    # 读取并验证JSON格式
    try:
        with open(repo_path, 'r', encoding='utf-8') as f:
            repo_data = json.load(f)
    except json.JSONDecodeError:
        log.error("Failed to decode JSON from the response.")
        sys.exit(1)
    
    # 检查必需的键是否存在
    required_keys = ['contact', 'id', 'patches', 'servers', 'title']
    if not all(key in repo_data for key in required_keys):
        log.error("The repo.js file is missing a necessary key")
        return
    
    # 检查并插入neighbors键
    if 'neighbors' not in repo_data:
        # 复制字典并插入新键
        new_repo_data = {}
        for key, value in repo_data.items():
            new_repo_data[key] = value
            if key == 'id':
                new_repo_data['neighbors'] = []
        repo_data = new_repo_data
    
    # 向neighbors中插入新的URL
    if mirror_repo_url not in repo_data['neighbors']:
        repo_data['neighbors'].append(mirror_repo_url)
    
    # 写回repo.js文件
    with open(repo_path, 'w', encoding='utf-8') as f:
        json.dump(repo_data, f, ensure_ascii=False, indent=4)
    
    log.succ(f"Add a new neighbor:{mirror_repo_url}")

# 保存当前 patch 下载任务状态
def save_add_info(mirror_dir: str, repo_id: str, repo_url: str, lp: list, dp: str):
    # 创建add_info数据结构
    add_info = {
        "repo": repo_id,
        "origin": repo_url,
        "patches_task": lp,
        "downloading": dp
    }

    # 确保mirror_dir路径存在
    if not os.path.exists(mirror_dir):
        os.makedirs(mirror_dir)

    # 将add_info转换为JSON数据并写入__add.json文件
    add_info_path = os.path.join(mirror_dir, "__add.json")
    with open(add_info_path, 'w', encoding='utf-8') as add_info_file:
        json.dump(add_info, add_info_file, ensure_ascii=False, indent=4)

# 载入未完成 patch 状态信息
def load_add_info(mirror_dir: str):
    add_info_path = os.path.join(mirror_dir, "__add.json")
    file_js_path = os.path.join(mirror_dir, "__files.js")
    # Check if the __add.json file exists
    if not os.path.exists(add_info_path):
        return None

    # Load the add info from the JSON file
    with open(add_info_path, 'r') as add_info_file:
        add_info = json.load(add_info_file)

    with open(file_js_path, 'r') as f:
        pf = json.load(f)
    # Fetch the info from the file
    repo_id = add_info.get("repo", "")
    repo_url = add_info.get("origin", "")
    lp = add_info.get("patches_task", [])
    dp = add_info.get("downloading", "")

    # Return the info
    return repo_id, repo_url, lp, dp, pf

# 删除临时 patch 状态信息
def clean_add_info(mirror_dir: str):
    add_info_path = os.path.join(mirror_dir, "__add.json")
    file_js_path = os.path.join(mirror_dir, "__files.js")

    if os.path.exists(add_info_path):
        os.remove(add_info_path)
    if os.path.exists(file_js_path):
        os.remove(file_js_path)

# 恢复上次因意外退出而中断的下载任务
async def backup_task(config: dict):
    mirror_dir = config['mirror_dir']
    log.info("Check if the last download task was interrupted...")
    load_res = load_add_info(mirror_dir)
    if not isinstance(load_res, tuple):
        log.info("No interrupt detected, skipping.")
        return
    else:
        repo_id, repo_url, lp, dp, pf = load_add_info(mirror_dir)
    log.info("Interrupted download detected! Recovering...")
    repo_dir = os.path.join(mirror_dir, repo_id)
    dp_dir = os.path.join(mirror_dir, dp)
    patch_url = urljoin(format_url(repo_url), dp)
    file_semaphore = asyncio.Semaphore(10)

    # 创建文件检查任务
    check_tasks = [check_file(pfn, checksum, dp_dir) for pfn, checksum in pf.items()]
    check_res = await asyncio.gather(*check_tasks)

    # 创建下载任务
    download_tasks = []
    for i, (pfn, checksum) in enumerate(pf.items()):
        if not check_res[i]:  # 只有在文件不存在或校验失败时才下载
            download_tasks.append(download_patch(patch_url, pfn, dp_dir, file_semaphore))
    await asyncio.gather(*download_tasks)

    await generate_mirror_info(mirror_dir, repo_url, repo_id, dp)

    # 完成队列剩余下载任务
    if lp:
        lap = lp.copy()
        for i in lp:
            if i in lap:
                lap.remove(i)
            save_add_info(mirror_dir, repo_id, repo_url, lap, i)
            await mirror_patch_from_repo(repo_url, repo_dir, repo_id, i)

    # 生成镜像站用 repo.js
    mirror_repo_url = format_url(urljoin(format_url(config['site_url']), repo_id))
    repo_js = await fetch_repo_info(repo_url)
    generate_repo_js(repo_js, repo_dir, repo_url)

    # 构建镜像站索引
    if repo_id != 'thpatch':
        thpatch_dir = os.path.join(config['mirror_dir'], config['thpatch'])
        build_index(thpatch_dir, repo_id, mirror_repo_url)

    # 清理状态记录文件
    clean_add_info(mirror_dir)

    user_option = input("Download Completed! Continue to add? (Y/n):")
    if user_option.upper() == 'Y':
        pass
    else:
        sys.exit(0)

async def main():
    # 载入用户设置
    try:
        config = load_config()
        if config == None:
            raise ValueError("Faild to load custom configure, Please restart the script.")
    except ValueError as e:
        log.error(f"{str(e)}")
        sys.exit(1)

    # 用户配置预处理
    mirror_dir = config['mirror_dir']

    # 恢复未完成的下载任务（若存在）
    await backup_task(config)

    # 用户输入 repo 或 patch 公共 URL
    base_url = input("Please input URL(Repo or Server):")
    base_url = format_url(base_url)
    am = IsRepoOrServer(base_url)

    repo_js = await fetch_repo_info(base_url, am)
    repo_id = repo_js['id']

    # 欲加入官方库（thpatch库）时所作预处理
    if repo_id == "thpatch":
        repo_id = config['thpatch']

    # 合成镜像站 repo 地址
    repo_dir = os.path.join(mirror_dir, repo_id)

    # 检测到输入的 URL 为 repo 地址
    try:
        lrmp = []
        if am == add_mode.ADD_REPO:
            lp = enumerate_patch(base_url)
            patch_input = input(f"Select the appropriate patch numbers(1-{len(lp)}) separated by commas and/or spaces, or leave input blank to select all options shown (Enter 'c' to cancel):")
            lu = re.split(r'[,\s]+',patch_input.strip())
            # 用户一次加入多个 patch
            if 'c' not in lu:
                lmp = []
                lap = []
                if lu[0] != '':
                    # 将字符串转换为整数，并过滤有效的下标
                    try:
                        indices = [int(i) for i in lu if i.isdigit()]
                        lmp = [lp[i-1] for i in indices if 0 <= i-1 < len(lp)]
                    except ValueError:
                        log.error("Invalid input. Please ensure all inputs are numbers or 'c'.")
                elif lp != []:
                    lmp = lp

                lap = lmp.copy()
                if lmp:
                    for i in lmp:
                        if i in lap:
                            lap.remove(i)
                        save_add_info(mirror_dir, repo_id, base_url, lap, i)
                        await mirror_patch_from_repo(base_url, repo_dir, repo_id, i)

                    lrmp = lmp

        # 检测到输入的 URL 为 patch 地址
        elif am == add_mode.ADD_PATCH:
            repo_url = urljoin(base_url, "..")
            pn = get_last_path_segment(base_url)
            save_add_info(mirror_dir, repo_id, repo_url, [], pn)
            await mirror_patch_from_repo(base_url, repo_dir, repo_id)
            lrmp = [pn]

        # 对不需要同步的 patch 进行处理
        if repo_id != config['thpatch'] and lrmp:
            remove_mirror_list(mirror_dir, repo_id, lrmp)
    except ValueError as v:
        log.error(f"{str(v)}")
        pass
    except Exception as e:
        log.error(f"An error occurred: {str(e)}")
        sys.exit(1)

    # 生成镜像站用 repo.js
    mirror_repo_url = format_url(urljoin(format_url(config['site_url']), repo_id))
    generate_repo_js(repo_js,repo_dir,mirror_repo_url)

    # 构建镜像站索引
    if repo_id != 'thpatch':
        thpatch_dir = os.path.join(config['mirror_dir'], config['thpatch'])
        build_index(thpatch_dir, repo_id, mirror_repo_url)

    # 清理状态记录文件
    clean_add_info(mirror_dir)

asyncio.run(main())