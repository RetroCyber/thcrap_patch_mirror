# 镜像站用添加补丁脚本
# 功能：
# 1.可直接输入补丁地址进行添加
# 2.给定仓库(repo)地址，列举其下所有补丁(patch)，选择添加
# 3.可自主选择是否加入镜像站同步列表（部分补丁是一次性更新）
import httpx
import asyncio
import os
import re
from color_logger import ColorLogger
from urllib.parse import urljoin, urlparse
from hashlib import sha256

log = ColorLogger().logger

# 获取 patch 文件列表信息
async def fetch_patch_file_info(base_url):

    # 合成 files.js 的完整 URL
    files_js_url = urljoin(base_url, 'files.js')

    # 获取 JSON 数据
    async with httpx.AsyncClient() as client:
        response = await client.get(files_js_url)
        response.raise_for_status()
        json_data = response.json()

        # 获取 patch 文件信息键值对，舍弃空值项（远端文件已删除）
        file_url_keys = [key for key, value in json_data.items() if value is not None]
        return file_url_keys

# 下载 patch 文件
async def download_patch(base_url, pfn, file_semaphore, rate_limit_kbps=500, max_retries=5):
    rate_limit_bps = rate_limit_kbps * 1024
    retry_count = 0
    success = False
    while retry_count < max_retries and not success:
        try:
            async with file_semaphore:
                file_url = urljoin(base_url, pfn)  # 合成文件的完整URL
                url_path = urlparse(file_url).path
                file_path = url_path.lstrip('/')  # 去除前导的 '/'
                file_url += "?=2233"
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
async def mirror_patch_from_repo(base_url,ipatch=""):
    if ipatch != '':
        ipatch = ipatch + '/'
    # 获取 patch 文件列表
    patch_url = base_url + ipatch
    log.info("Mirroring {} ...".format(patch_url.split('/')[-2] if len(patch_url.split('/')) > 1 else None))
    flist = await fetch_patch_file_info(patch_url)
    # 设置最大并发数
    semaphore = asyncio.Semaphore(10)
    tasks = [download_patch(base_url, patch_url + pfn, semaphore) for pfn in flist]
    await asyncio.gather(*tasks)

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
                    return None

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
                        log.error("Invalid URL, please check it to make sure is correct.")
                        return None
            
    except httpx.RequestError as exc:
        log.error(f"An error occurred while requesting {url}: {exc}")

#枚举 repo 包含的 patch，并返回 patch 列表
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

async def main():
    print("Please input URL(Repo or Server):",end=' ')
    base_url = input()
    mode_status = IsRepoOrServer(base_url)
    # 检测到输入的 URL 为 repo 地址
    if mode_status == 1:
        plist = enumerate_patch(base_url)
        print("Select the appropriate patch numbers(1-{}) separated by commas and/or spaces, or leave input blank to select all options shown (Enter 'c' to cancel):".format(len(plist)),end='')
        patch_input = input()
        lpmirror = re.split(r'[,\s]+',patch_input.strip())
        print(lpmirror)
        if 'c' not in lpmirror:
            if lpmirror[0] != '':
                for i in lpmirror:
                    i = int(i)
                    if i>=1 and i <= len(plist):
                        await mirror_patch_from_repo(base_url,plist[i-1])
                    else:
                        log.error("Invalid number:{} , Can't find the patch specificed.".format(i))
            elif plist != []:
                for i in plist:
                    await mirror_patch_from_repo(base_url,i)
    # 检测到输入的 URL 为 patch 地址
    elif mode_status == 2:
        # 获取 JSON 数据
        await mirror_patch_from_repo(base_url)

os.environ["http_proxy"] = "http://127.0.0.1:7890"
os.environ["https_proxy"] = "http://127.0.0.1:7890"

asyncio.run(main())