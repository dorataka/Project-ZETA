import os
import pydicom
import numpy as np
import SimpleITK as sitk
from PyQt6.QtCore import QThread, pyqtSignal

class DicomScanWorker(QThread):
    finished = pyqtSignal(dict, str)
    error = pyqtSignal(str)

    def __init__(self, folder_path):
        super().__init__()
        self.folder_path = folder_path

    def run(self):
        try:
            files = os.listdir(self.folder_path)
            temp_series_info = {}
            for f in files:
                full_path = os.path.join(self.folder_path, f)
                if os.path.isdir(full_path): continue
                try:
                    ds = pydicom.dcmread(full_path, stop_before_pixels=True)
                    uid = ds.get('SeriesInstanceUID', 'Unknown')
                    desc = ds.get('SeriesDescription', 'No Description')
                    modality = ds.get('Modality', '??')
                    if uid not in temp_series_info:
                        temp_series_info[uid] = {'desc': desc, 'modality': modality, 'files': []}
                    temp_series_info[uid]['files'].append(full_path)
                except: continue
            
            if not temp_series_info: self.error.emit("No DICOM files found.")
            else: self.finished.emit(temp_series_info, f"FOUND {len(temp_series_info)} SERIES.")
        except Exception as e: self.error.emit(str(e))

class SeriesLoadWorker(QThread):
    finished = pyqtSignal(list, list) 
    progress = pyqtSignal(int)

    def __init__(self, file_paths):
        super().__init__()
        self.file_paths = file_paths

    def run(self):
        loaded_slices = []
        total = len(self.file_paths)
        for i, f_path in enumerate(self.file_paths):
            try:
                ds = pydicom.dcmread(f_path)
                if hasattr(ds, 'PixelData'): loaded_slices.append(ds)
            except: pass
            if i % 5 == 0: self.progress.emit(int((i / total) * 100))
        
        loaded_slices.sort(key=lambda x: int(x.InstanceNumber) if 'InstanceNumber' in x else x.filename)
        pixel_spacing = None
        if loaded_slices and 'PixelSpacing' in loaded_slices[0]:
            pixel_spacing = [float(x) for x in loaded_slices[0].PixelSpacing]
        self.finished.emit(loaded_slices, pixel_spacing)

# --- ★修正: MPR構築ワーカー (Float32 & 背景色対策) ---
class MprBuilderWorker(QThread):
    finished = pyqtSignal(np.ndarray, tuple)
    progress = pyqtSignal(int)

    def __init__(self, file_paths):
        super().__init__()
        self.file_paths = file_paths

    def run(self):
        try:
            self.progress.emit(5)
            
            # 1. Z座標でソート
            sorted_files = []
            for i, f in enumerate(self.file_paths):
                try:
                    ds = pydicom.dcmread(f, stop_before_pixels=True)
                    if 'ImagePositionPatient' in ds:
                        z = float(ds.ImagePositionPatient[2])
                        sorted_files.append((z, f))
                    else:
                        sorted_files.append((float(i), f))
                except: pass
                if i % 20 == 0: self.progress.emit(5 + int((i/len(self.file_paths))*10))
            
            sorted_files.sort(key=lambda x: x[0])
            files_to_read = [x[1] for x in sorted_files]
            
            self.progress.emit(20)

            # 2. SimpleITKで読み込み
            reader = sitk.ImageSeriesReader()
            reader.SetFileNames(files_to_read)
            reader.GlobalWarningDisplayOff()
            image_sitk = reader.Execute()
            
            self.progress.emit(40)

            # --- ★重要変更: Float32に変換 ---
            # これにより、リサンプリング時の計算誤差やオーバーフローを防ぐ
            image_sitk = sitk.Cast(image_sitk, sitk.sitkFloat32)

            # --- 背景色の決定 ---
            # 統計フィルタで最小値を取得 (これが「真っ黒」の値)
            stats = sitk.StatisticsImageFilter()
            stats.Execute(image_sitk)
            min_val = stats.GetMinimum()

            # 3. 幾何学的補正 (Oblique -> Orthogonal)
            direction = image_sitk.GetDirection()
            identity = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
            
            is_oblique = False
            for i in range(9):
                if abs(direction[i] - identity[i]) > 1e-5:
                    is_oblique = True; break
            
            if is_oblique:
                orig_spacing = image_sitk.GetSpacing()
                orig_origin = image_sitk.GetOrigin()
                orig_size = image_sitk.GetSize()
                
                resampler = sitk.ResampleImageFilter()
                resampler.SetOutputDirection(identity)
                resampler.SetOutputOrigin(orig_origin)
                resampler.SetOutputSpacing(orig_spacing)
                resampler.SetSize(orig_size)
                
                # ★重要: デフォルト値を画像の最小値にする
                # これで、回転してできた隙間が「黒」で埋められる
                resampler.SetDefaultPixelValue(min_val)
                
                # Float32なので画素値は維持される
                resampler.SetOutputPixelType(sitk.sitkFloat32)
                resampler.SetInterpolator(sitk.sitkLinear)
                
                image_sitk = resampler.Execute(image_sitk)
            
            self.progress.emit(80)

            volume = sitk.GetArrayFromImage(image_sitk)
            sp_x, sp_y, sp_z = image_sitk.GetSpacing()
            
            self.progress.emit(100)
            self.finished.emit(volume, (sp_z, sp_y, sp_x))

        except Exception as e:
            print(f"MPR Build Failed: {e}")
            self.finished.emit(None, (1,1,1))