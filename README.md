# 20250625 update : add PH_BAC exec build  

conda create -n pydealer_test python=3.10.12 -y  
conda activate pydealer_test  
python -m pip install -U pip  
pip install -r requirements.txt  

smoke test : python main.py  

pyinstaller --clean --onedir --console --name ImageDetector_PH --hidden-import=tkinter --runtime-hook=hook_force_stdlib_distutils.py --add-data "config.xml;." --add-data "models;models" main.py    
<!-- pyinstaller --clean --noconfirm ImageDetector_PH.spec   -->
如dist裡面的ImageDetector_PH資料夾內還是沒有config.xml或models資料夾，請將外面專案資料夾的這兩份檔案複製進去  => 目前都是手動放置  

# PyDealerClient

image recognition which sample live video and send result data to Dealer by net socket.

# release note
2022/11/2 v1.5.6
1. fix��ͼ�ϴ��ͺ�16s.
2. log add gmSaveFinalResult and gmCount.
3. support samba folder to save snapshot images.
2022/10/22 v1.5.1
1. ���������ͼƬ.
# if len(save_descjudge) > 0:
#     self.imageSaver.save(gmcode, int(pos.index), save_descjudge, save_scorejudge, predict_image_save, False)
imageSaver = ImageSaver(cfg.save_folder)  //������ͼƬ����Ŀ¼
2. �����ļ��޸�
	<save folder="./predict_images" autoUpload="0"/>

2022/10/5 v1.5.0
    only produce one full image and upload to FTP Server.

2022/8/16 v1.4.2
    init as baseline.

