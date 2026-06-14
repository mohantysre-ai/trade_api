@echo off
cd /d d:\trade_api\iros-terminal
git add .gitignore
git commit -F commit_msg3.txt
rm commit_msg.txt
rm commit_msg2.txt
rm commit_msg3.txt
git add -A
git commit -m "cleanup: remove temp commit message files"