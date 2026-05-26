# 公司电脑代码同步到 GitHub 操作清单

适用于以下情况：

- 公司电脑上的代码不确定有没有推送到 GitHub
- 代码可能只在本地 Git 仓库里
- 代码可能推到了公司 GitLab、Gitea、自建 Git 或其他远端
- 想让 AI 帮你判断代码历史在哪里，并迁移到 GitHub

重要提醒：如果代码属于公司项目，请先确认你有权限把它同步到 GitHub，尤其是同步到个人账号或公开仓库。

## 一、先确认当前目录是不是 Git 仓库

在公司电脑打开项目目录，执行：

```bash
git status
```

如果看到类似下面内容，说明这是 Git 仓库：

```text
On branch main
Your branch is up to date with 'origin/main'.
```

如果看到下面内容，说明当前目录不是 Git 仓库：

```text
fatal: not a git repository
```

这种情况下先不要乱操作，确认是否进错目录。可以到项目上一级目录找找是否有真正的项目目录。

## 二、收集信息发给 AI 判断

在项目目录依次执行：

```bash
git remote -v
```

```bash
git branch -a
```

```bash
git log --oneline --decorate --graph --all --max-count=50
```

```bash
git reflog --date=local --max-count=50
```

把这四段输出发给 AI，让 AI 先判断：

- 代码是否已经连接远端仓库
- 远端是不是 GitHub
- 是否存在未推送的本地提交
- 是否存在其他分支
- 是否存在可以恢复的历史提交

## 三、判断常见情况

### 情况 1：已经连接 GitHub

如果 `git remote -v` 显示类似：

```text
origin  https://github.com/你的账号/仓库名.git (fetch)
origin  https://github.com/你的账号/仓库名.git (push)
```

说明它已经连接 GitHub。

继续检查有没有未推送提交：

```bash
git status
```

如果提示本地分支 ahead，例如：

```text
Your branch is ahead of 'origin/main' by 3 commits.
```

说明本地有 3 个提交还没推送。

推送当前分支：

```bash
git push origin HEAD
```

如果还有其他分支需要一起推送：

```bash
git push origin --all
git push origin --tags
```

### 情况 2：连接的是公司 Git，不是 GitHub

如果 `git remote -v` 显示类似：

```text
origin  https://gitlab.company.com/team/project.git (fetch)
origin  https://gitlab.company.com/team/project.git (push)
```

说明代码可能推到了公司 Git。

如果你有权限迁移到 GitHub，可以先在 GitHub 创建一个新仓库，然后在公司电脑执行：

```bash
git remote add github https://github.com/你的账号/你的仓库.git
```

推送所有分支和标签：

```bash
git push github --all
git push github --tags
```

这样可以保留原来的 `origin`，同时新增一个 GitHub 远端 `github`。

### 情况 3：只有本地 Git 仓库，没有远端

如果 `git remote -v` 没有任何输出，说明当前仓库没有配置远端。

先确认本地是否有提交历史：

```bash
git log --oneline --decorate --graph --all --max-count=50
```

如果能看到提交历史，可以在 GitHub 创建新仓库，然后执行：

```bash
git remote add origin https://github.com/你的账号/你的仓库.git
git push origin --all
git push origin --tags
```

### 情况 4：只有源码，没有 Git 历史

如果当前项目没有 `.git`，并且找不到原来的 Git 仓库，那么只能把当前源码作为新项目上传，不能恢复以前的提交历史。

操作方式：

```bash
git init
git add .
git commit -m "initial import"
git branch -M main
git remote add origin https://github.com/你的账号/你的仓库.git
git push -u origin main
```

注意：这种方式只会上传当前代码状态，不会保留以前的 commit 历史。

## 四、迁移前建议先做一个本地备份

如果你担心误操作，可以先在公司电脑项目目录外复制一份完整文件夹。

也可以用 Git 生成一个完整备份包：

```bash
git bundle create project-backup.bundle --all
```

这个 `project-backup.bundle` 包含当前仓库的分支和提交历史。之后可以用下面命令恢复：

```bash
git clone project-backup.bundle restored-project
```

## 五、让 AI 帮你判断时使用的提问模板

```text
我在公司电脑上有一个项目，我不确定它有没有完整推送到 GitHub，也不确定是不是推到了其他远端。

下面是我收集到的信息：

git remote -v：
<粘贴输出>

git branch -a：
<粘贴输出>

git log --oneline --decorate --graph --all --max-count=50：
<粘贴输出>

git reflog --date=local --max-count=50：
<粘贴输出>

请你先不要让我直接执行迁移命令，先帮我判断：
1. 代码历史现在在哪里
2. 是否有未推送的本地提交
3. 是否有其他分支需要同步
4. 是否能完整迁移到 GitHub
5. 如果可以，请给出最稳妥的命令
6. 如果不可以，请告诉我缺少什么信息
```

## 六、迁移完成后的检查

推送完成后，在公司电脑执行：

```bash
git remote -v
```

```bash
git status
```

```bash
git log --oneline --decorate --graph --all --max-count=20
```

然后打开 GitHub 仓库页面检查：

- 文件是否完整
- 分支是否完整
- 提交历史是否存在
- tags 是否存在
- 仓库是否设置为正确的公开或私有状态

## 七、不要做的事情

- 不要使用 `git reset --hard`，除非你非常确定并且已经备份
- 不要删除 `.git` 文件夹
- 不要在不清楚远端含义时执行强制推送
- 不要把公司敏感代码推到个人公开仓库
- 不要把 GitHub 密码发给 AI 或任何人
