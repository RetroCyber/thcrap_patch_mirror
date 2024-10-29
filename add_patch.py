# 镜像站用添加补丁脚本
# 功能：
# 1.可直接输入仓库(repo)或补丁(patch)的 URL 进行添加
# 2.给定仓库(repo) URL，列举其下所有补丁(patch)，选择添加
# 3.引导用户生成自定义配置文件，可供镜像脚本(mirror_patch.py)使用
# 4.自动调用 repo_update.py 构建补丁，允许thcrap直接下载使用
import httpx
import json
import asyncio
import os
import re
import sys
from repo_update import repo_build, enter_missing
from color_logger import ColorLogger
from urllib.parse import urljoin, urlparse
from hashlib import sha256

log = ColorLogger().logger

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
def format_url(url):
    if not url.endswith('/'):
        return url + '/'
    return url

# 获取 URL 最后一级
def get_last_path_segment(url):
    parsed_url = urlparse(url)
    path = parsed_url.path

    # Remove trailing slash if it exists
    if path.endswith('/'):
        path = path[:-1]

    # Split the path by '/' and get the last segment
    last_segment = path.split('/')[-1]
    return last_segment

# 获取 patch 文件列表信息
async def fetch_patch_file_info(patch_url):

    # 合成 files.js 的完整 URL
    files_js_url = urljoin(format_url(patch_url), "files.js?=2233")

    # 获取 JSON 数据
    async with httpx.AsyncClient() as client:
        response = await client.get(files_js_url)
        response.raise_for_status()
        json_data = response.json()

        # 获取 patch 文件信息键值对，舍弃空值项（远端文件已删除）
        file_url_keys = [key for key, value in json_data.items() if value is not None]
        return file_url_keys

# 获取 repo 信息（repo.js 内容）
async def fetch_repo_info(url, mode):
    async with httpx.AsyncClient() as client:
        try:
            if mode == 1:
                # Mode 1: Directly append 'repo.js' to the repo URL
                repo_js_url = urljoin(url, 'repo.js')
            elif mode == 2:
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
async def fetch_patch_ver(patch_ver):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(patch_ver)
            response.raise_for_status()  # 如果请求失败则抛出异常
            return sha256(response.content).hexdigest()
        except Exception as e:
            log.error(f"Error accessing {patch_ver}: {e}")
            sys.exit(1)

# 生成镜像站用 repo.js
def generate_repo_js(repo_js, repo_dir, servers):
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
async def download_patch(base_url, pfn, patch_dir, file_semaphore, rate_limit_kbps=1024, max_retries=5):
    rate_limit_bps = rate_limit_kbps * 1024
    retry_count = 0
    success = False
    while retry_count < max_retries and not success:
        try:
            async with file_semaphore:
                file_url = urljoin(format_url(base_url), f"{pfn}?=2233") # 合成文件的完整URL
                file_path = os.path.join(patch_dir,pfn)  # 合成文件保存路径
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
async def mirror_patch_from_repo(base_url, repo_dir, repo_id, ipatch=""):

    # 获取 patch 文件列表
    patch_url = urljoin(format_url(base_url), ipatch)
    pn = get_last_path_segment(patch_url)
    log.info(f"Mirroring {pn} ...")
    flist = await fetch_patch_file_info(patch_url)

    # 生成补丁路径
    patch_dir = os.path.join(repo_dir, pn)

    # 设置最大并发数
    semaphore = asyncio.Semaphore(10)
    tasks = [download_patch(patch_url, pfn, patch_dir, semaphore) for pfn in flist]
    await asyncio.gather(*tasks)

    # 生成 patch 版本文件
    repo_url = urljoin(format_url(patch_url),'..')
    mirror_dir = os.path.dirname(repo_dir)
    await generate_mirror_info(mirror_dir, repo_url, repo_id, pn)

# 生成镜像 repo 版本信息
async def generate_mirror_info(mirror_dir, repo_origin, repo_id, patch):

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
def IsRepoOrServer(url):
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
                    return 1
                else:

                    # 检查 base_url + files.js 是否可访问
                    files_js_url = url.rstrip('/') + '/files.js'
                    response = client.get(files_js_url, timeout=10)
                    if response.status_code == 200:
                        log.succ("Find files.js. Downloading...")
                        return 2
                    else:
                        raise ValueError("Invalid URL, please check it to make sure is correct.")
    except httpx.RequestError as exc:
        log.error(f"An error occurred while requesting {url}: {exc}")
        sys.exit(1)
    except ValueError as e:
        log.error(f"{str(e)}")
        sys.exit(1)

# 枚举 repo 包含的 patch ，并返回 patch 列表
def enumerate_patch(url):
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
def delete_mirror_item(mirror_dir, repo_id, patch):
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

def remove_mirror_list(mirror_dir, repo_id, patch_data):
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
                    raise ValueError(f"Invalid option: {i}, skipped.")
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
def build_index(thpatch_dir, repo_id, mirror_repo_url):
    log.info(f"Adding index for {repo_id}...")
    # 构建repo.js文件的路径
    repo_path = os.path.join(thpatch_dir, 'repo.js')
    
    # 检查repo.js文件是否存在
    if not os.path.exists(repo_path):
        log.warning("The main server(thpatch repo) has not been established, skipped.")
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

    # 用户输入 repo 或 patch 公共 URL
    base_url = input("Please input URL(Repo or Server):")
    base_url = format_url(base_url)
    mode = IsRepoOrServer(base_url)

    repo_js = await fetch_repo_info(base_url, mode)
    repo_id = repo_js['id']

    # 欲加入官方库（thpatch库）时所作预处理
    if repo_id == "thpatch":
        repo_id = config['thpatch']

    # 合成镜像站 repo 地址
    repo_dir = os.path.join(mirror_dir, repo_id)

    # 检测到输入的 URL 为 repo 地址
    try:
        patches_to_remove = []
        if mode == 1:
            plist = enumerate_patch(base_url)
            patch_input = input(f"Select the appropriate patch numbers(1-{len(plist)}) separated by commas and/or spaces, or leave input blank to select all options shown (Enter 'c' to cancel):")
            lpmirror = re.split(r'[,\s]+',patch_input.strip())
            # 用户一次加入多个 patch
            if 'c' not in lpmirror:
                if lpmirror[0] != '':
                    lpatch = []
                    for i in lpmirror:
                        i = int(i)
                        if i>=1 and i <= len(plist):
                            lpatch.append(plist[i-1])
                            await mirror_patch_from_repo(base_url, repo_dir, repo_id, plist[i-1])
                        else:
                            raise ValueError(f"Invalid option: {i}, Skipped.")
                    patches_to_remove = lpatch  
                elif plist != []:
                    for i in plist:
                        await mirror_patch_from_repo(base_url, repo_dir, repo_id, i)
                    patches_to_remove = plist

        # 检测到输入的 URL 为 patch 地址
        elif mode == 2:
            await mirror_patch_from_repo(base_url, repo_dir, repo_id)
            patch_name = get_last_path_segment(base_url)
            patches_to_remove = [patch_name]

        # 对不需要同步的 patch 进行处理
        if repo_id != config['thpatch'] and patches_to_remove:
            remove_mirror_list(mirror_dir, repo_id, patches_to_remove)
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

# os.environ["http_proxy"] = "http://127.0.0.1:7890"
# os.environ["https_proxy"] = "http://127.0.0.1:7890"

asyncio.run(main())