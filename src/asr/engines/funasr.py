"""
FunASR 引擎實現
阿里達摩院的 FunASR，專注中文識別
"""

from typing import Dict, Any

from src.utils.logging import logger
from src.asr.base import BaseASR


class FunASR(BaseASR):
    """
    FunASR 引擎（阿里達摩院）
    
    專注中文語音識別，速度快，準確度高
    """
    
    def __init__(self, config=None, model_name: str = "paraformer-zh"):
        """
        初始化 FunASR
        
        Args:
            config: 配置物件
            model_name: 模型名稱（預設 paraformer-zh）
        """
        super().__init__(config)
        
        self.model_name = model_name
        self.model = None
        
        logger.info(f'[FunASR] 模型: {model_name}')
    
    def _load_model(self):
        """載入 FunASR 模型"""
        try:
            from funasr import AutoModel
            logger.info(f'[FunASR] 正在載入模型: {self.model_name}')
            self.model = AutoModel(model=self.model_name)
            logger.info('[FunASR] 模型載入成功')
            
        except ImportError:
            raise ImportError(
                "請安裝 FunASR:\n"
                "  pip install funasr"
            )
        except Exception as e:
            logger.error(f'[FunASR] 模型載入失敗: {e}')
            raise
    
    def _transcribe(self, audio_path: str) -> Dict[str, Any]:
        """
        使用 FunASR 識別音訊
        
        Args:
            audio_path: 音訊檔案路徑
            
        Returns:
            識別結果字典
        """
        result = self.model.generate(input=audio_path)
        
        if result and len(result) > 0:
            text = result[0].get("text", "")
            return {
                "text": text.strip(),
                "language": "zh"
            }
        
        return {
            "text": "",
            "language": "zh"
        }
    
    def get_info(self) -> Dict[str, Any]:
        """獲取引擎資訊"""
        info = super().get_info()
        info.update({
            "model_name": self.model_name
        })
        return info
