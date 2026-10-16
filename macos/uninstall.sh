#!/bin/bash
# 제거: 폴더 감시 해제 (모델과 변환 결과는 남겨둠)
LABEL="com.lecture-transcriber"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Folder watcher removed. Delete models/ to free ~4.7 GB."
