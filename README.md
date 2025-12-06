# Project Z.E.T.A.
**Zero-latency Executive Tomography Algorithm**

![License](https://img.shields.io/badge/license-MIT-blue.svg) ![Python](https://img.shields.io/badge/python-3.10%2B-green) ![Qt](https://img.shields.io/badge/PyQt-6.0%2B-success)

## Overview
**Project Z.E.T.A.** は、Python (PyQt6) で開発された高性能デスクトップDICOMビューアーです。
臨床医による個人開発プロジェクトとして、既存のビューアーにはない柔軟性と、SFメカニック（G.U.N.D.A.M. OS）にインスパイアされた没入感のあるUIを目指して設計されています。

「高速な画像展開」と「実臨床に即した操作系（PACSライクなマウス操作）」を両立しています。

## System Capabilities (Features)
* **High-Speed Rendering:** `pydicom` と `numpy` を活用した高速な画像展開とCT値（HU）計算。
* **Multi-Series Support:** フォルダ内のDICOMシリーズ（Scout, Arterial, Bone etc.）を自動分類し、サイドバーから瞬時に切り替え可能。
* **PACS Standard Controls:** 放射線科医・臨床医が慣れ親しんだマウス操作系を完全再現。
* **Smart Drag & Drop:** フォルダ、またはファイルをドロップするだけで、関連するシリーズ全体を自動ロード。
* **Custom Rendering Engine:** `QLabel` に依存しない独自の描画キャンバスにより、スムーズなパン（移動）とウィンドウニングを実現。
* **Startup Sequence:** 起動時にハードウェア（GPU等）チェックを模したコンソールアニメーションを搭載。

## Requirement
* **OS:** Windows 10 / 11 (Recommended)
* **Python:** 3.9 or higher
* **GPU:** NVIDIA RTX Series (Recommended for boot sequence immersion)

## Installation

    # Clone the repository
    git clone [https://github.com/dorataka/Project-ZETA.git](https://github.com/dorataka/Project-ZETA.git)

    # Move to directory
    cd Project-ZETA

    # Install dependencies
    pip install -r requirements.txt

## Usage

### 1. Launch

    python main.py

### 2. Load Data
* **Drag & Drop:** DICOMファイルが含まれるフォルダ、またはファイルをウィンドウにドロップしてください。
* **Open Folder:** サイドバーのボタンからディレクトリを選択してください。

### 3. Controls (Mouse Operations)
実臨床のPACS（読影端末）と同様の操作系を実装しています。

| Input | Action | Description |
| :--- | :--- | :--- |
| **Right Drag** | **Window / Level** | 上下でLevel（輝度）、左右でWidth（コントラスト）を調整 |
| **Left Drag** | **Pan** | 画像の平行移動 |
| **Middle Drag** | **Paging** | ホイールボタンを押しながら上下移動でスタック（ページ）送り |
| **Wheel Scroll** | **Paging** | スライスの切り替え |
| **Sidebar Click** | **Series Change** | 別の撮影シリーズへ切り替え |

## Disclaimer (免責事項)
本ソフトウェアは研究・学習・個人利用を目的として開発されています。
**薬機法（旧薬事法）における医療機器プログラムとしての承認は受けていません。**
確定診断や治療方針の決定など、臨床判断の主たる根拠として使用することは避けてください。あくまで補助的なツールとしてご活用ください。

## Author
* **Developer:** dorataka
* **Role:** Clinical Physician / Developer
