import os
import pydicom
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
                    uid = ds.SeriesInstanceUID if 'SeriesInstanceUID' in ds else 'Unknown'
                    desc = ds.SeriesDescription if 'SeriesDescription' in ds else 'No Description'
                    modality = ds.Modality if 'Modality' in ds else '??'
                    
                    if uid not in temp_series_info:
                        temp_series_info[uid] = {'desc': desc, 'modality': modality, 'files': []}
                    temp_series_info[uid]['files'].append(full_path)
                except:
                    continue
            
            if not temp_series_info:
                self.error.emit("No DICOM files found.")
            else:
                self.finished.emit(temp_series_info, f"FOUND {len(temp_series_info)} SERIES.")
        except Exception as e:
            self.error.emit(str(e))

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
                if hasattr(ds, 'PixelData'):
                    loaded_slices.append(ds)
            except:
                pass
            if i % 10 == 0:
                self.progress.emit(int((i / total) * 100))

        try:
            loaded_slices.sort(key=lambda x: int(x.InstanceNumber))
        except:
            loaded_slices.sort(key=lambda x: x.filename)
            
        pixel_spacing = None
        if loaded_slices:
            if 'PixelSpacing' in loaded_slices[0]:
                pixel_spacing = [float(x) for x in loaded_slices[0].PixelSpacing]

        self.finished.emit(loaded_slices, pixel_spacing)