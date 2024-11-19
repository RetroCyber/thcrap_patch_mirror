## v1.1

Using UTF-8 codepage in scripts.

### Add patch script (add_patch.py)

* Modify the URL input prompt to improve accuracy.

---

在脚本中使用UTF-8代码页

### 补丁添加脚本（Add_patch.py）

* 修改输入URL提示以提升准确性

## v1.0

### Add patch script (add_patch.py)

* You can directly input the URL of the repository (`repo`) or `patch` to add

* When a `repo` URL is given, list all patches under it for selection to add

* Guide users to generate custom configuration files for use by the mirror script (`mirror_patch.py`)

* Automatically call `repo_update.py` to build patches, allowing [thcrap](https://github.com/thpatch/thcrap) to download and use directly

* If an unexpected interruption occurs during `patch` addition, it can be resumed when running again

### Mirror patch script (mirror_repo.py)

* Read the repository (`repo`) version information and compare it with the origin server

* Compare the differences between the origin server and the `repo` file list

* Automatically download or clean up changed files

* Automatically update version information

* Update patch by patch and update version information in real time

* If the mirror update process is interrupted due to an accident, the unfinished update task will be automatically completed in the next update cycle

---

### 补丁添加脚本（Add_patch.py）

* 可直接输入仓库(`repo`)或补丁(`patch`)的 URL 以进行添加

* 给定仓库(repo)URL时，列举其下所有补丁(patch)以选择添加

* 引导用户生成自定义配置文件，可供镜像脚本(`mirror_patch.py`)使用

* 自动调用`repo_update.py`构建补丁，允许[thcrap](https://github.com/thpatch/thcrap)直接下载使用

* 若添加补丁过程中发生意外中断，再次运行时可恢复

### 镜像补丁脚本（mirror_repo.py）

* 读取仓库(`repo`)版本信息，与源服务器做对比

* 比较源服务器与`repo`文件列表的差异

* 自动下载或清理变动文件

* 自动更新版本信息

* 逐个补丁(`patch`)更新，并能够实时更新版本信息

* 若镜像更新过程因意外而中断，在下一更新周期时自动完成未完成的更新任务