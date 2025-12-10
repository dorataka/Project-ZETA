import numpy as np
from scipy.ndimage import map_coordinates

def get_resampled_slice(volume, center, right_vec, down_vec, normal_vec, width, height, spacing, thickness_mm=0.0, mode='AVG'):
    """
    3Dボリュームから任意の断面を切り出す（MPR/MIP対応版）
    高速化のため、Pythonのループを使わずNumpyのブロードキャスト機能を使用。
    
    :param volume: 3D画像データ (Z, Y, X)
    :param center: 断面の中心座標 (cx, cy, cz)
    :param right_vec: 画像の右方向ベクトル (vx, vy, vz) ※スケーリング済みであること
    :param down_vec: 画像の下方向ベクトル (vx, vy, vz) ※スケーリング済みであること
    :param normal_vec: 断面の法線（奥行き）ベクトル (vx, vy, vz) ※スケーリング済みであること
    :param width: 出力画像の幅
    :param height: 出力画像の高さ
    :param spacing: ボクセルスペーシング (sz, sy, sx)
    :param thickness_mm: スラブ厚 (mm)
    :param mode: 'AVG', 'MIP', 'MinIP'
    """
    
    # 1. 2D平面のグリッド座標を作成 (Height, Width)
    xs = np.arange(-width // 2, width // 2)
    ys = np.arange(-height // 2, height // 2)
    grid_x, grid_y = np.meshgrid(xs, ys) # shape: (H, W)
    
    # 2. 厚み方向のオフセット座標を作成 (Depth)
    z_offsets = np.array([0.0])
    
    if thickness_mm > 0:
        # 簡易的に「normal_vec 1個分 = 物理サイズ sp_x (1px)」とみなしてステップ数を計算
        # (呼び出し元で vectors が物理サイズ補正されている前提)
        sp_x = spacing[2] if len(spacing) > 2 else 1.0
        if sp_x <= 0: sp_x = 1.0
        
        # 厚みを満たすのに必要なステップ数
        steps = int(thickness_mm / sp_x)
        if steps > 0:
            z_offsets = np.arange(-steps // 2, steps // 2 + 1)
    
    # 3. 3次元的なサンプリンググリッドを作成 (Broadcasting)
    # これにより (Depth, Height, Width) の全座標を一括計算する準備をする
    
    # grid_x: (H, W) -> (1, H, W)
    grid_x_3d = grid_x[np.newaxis, :, :]
    grid_y_3d = grid_y[np.newaxis, :, :]
    
    # z_offsets: (D) -> (D, 1, 1)
    z_offs_3d = z_offsets[:, np.newaxis, np.newaxis]
    
    # 中心座標とベクトル成分の展開
    cx, cy, cz = center
    rx, ry, rz = right_vec
    dx, dy, dz = down_vec
    nx, ny, nz = normal_vec
    
    # 4. 座標計算 (Center + Right + Down + Normal)
    # 結果は (Depth, Height, Width) の形状を持つ3D座標配列になる
    sample_x = cx + (grid_x_3d * rx) + (grid_y_3d * dx) + (z_offs_3d * nx)
    sample_y = cy + (grid_x_3d * ry) + (grid_y_3d * dy) + (z_offs_3d * ny)
    sample_z = cz + (grid_x_3d * rz) + (grid_y_3d * dz) + (z_offs_3d * nz)
    
    # 5. マッピング実行
    # map_coordinates は (coords, ...) を受け取る。coordsのshapeは (3, D, H, W)
    # volumeの並びは (Z, Y, X) なので、その順序で渡す
    coords = np.array([sample_z, sample_y, sample_x])
    
    # 背景色の決定（MinIPなどで白くならないよう、ボリュームの最小値で埋める）
    bg_value = np.min(volume)
    
    # 補間実行
    # mode='constant', cval=bg_value により、範囲外を黒（または最小値）で埋める
    slab_data = map_coordinates(volume, coords, order=1, mode='constant', cval=bg_value)
    
    # 6. 投影処理 (Depth方向 = axis 0 を潰す)
    if mode == 'MIP':
        result = np.max(slab_data, axis=0)
    elif mode == 'MinIP':
        result = np.min(slab_data, axis=0)
    else: # AVG
        result = np.mean(slab_data, axis=0)
        
    return result.astype(np.float32)

def get_rotation_matrix(axis, angle_deg):
    """
    指定軸周りの回転行列を取得
    """
    rad = np.radians(angle_deg)
    c = np.cos(rad)
    s = np.sin(rad)
    
    if axis == 'z':
        return np.array([
            [ c, -s,  0],
            [ s,  c,  0],
            [ 0,  0,  1]
        ])
    elif axis == 'x':
        return np.array([
            [ 1,  0,  0],
            [ 0,  c, -s],
            [ 0,  s,  c]
        ])
    elif axis == 'y':
        return np.array([
            [ c,  0,  s],
            [ 0,  1,  0],
            [-s,  0,  c]
        ])
    return np.eye(3)