# 把看板发布到 GitHub Pages

看板 `board/valuation_board.html` 是自包含的单文件，数据内嵌、没有外部依赖，所以发布到 Pages 很简单，不需要构建，也不需要数据库。

## 从 docs 目录发布

改动最小的一种做法。

先把看板复制成 `docs/index.html`：

```powershell
copy board\valuation_board.html docs\index.html
```

然后提交并推送：

```powershell
git add docs/index.html
git commit -m "publish board to GitHub Pages"
git push
```

最后打开仓库的 Settings、Pages，Source 选 Deploy from a branch，Branch 选 main，目录选 `/docs`，保存。等一到两分钟，访问：

```
https://<用户名>.github.io/<仓库名>/
```

## 从仓库根目录发布

把看板放到仓库根，命名成 `index.html`：

```powershell
copy board\valuation_board.html index.html
git add index.html
git commit -m "publish board at root"
git push
```

然后 Settings、Pages 里 Source 选 Deploy from a branch，Branch 选 main，目录选 `/ (root)`。

## 用独立分支发布

不想动仓库结构的话，可以开一个孤儿分支。

```powershell
git checkout --orphan gh-pages
git rm -rf --cached .
copy board\valuation_board.html index.html
git add index.html
git commit -m "gh-pages: board"
git push -u origin gh-pages
git checkout main
```

然后 Settings、Pages 里 Source 选 Deploy from a branch，Branch 选 gh-pages，目录选 `/ (root)`。

页面是纯静态的 HTML、JS 和 SVG，Pages 直接就能跑，访问者不用装 Python。想换一个快照日，在本地重跑 `python board/make_board.py --vdate <YYYY-MM-DD>`，把新的 HTML 覆盖过去再推送。组内分享也可以直接用文件本身，把 `board/valuation_board.html` 发微信或邮件，对方双击就能看。
