import os
import requests
# API主机地址,默认为https://api.commadotai.com
API_HOST = os.getenv('API_HOST', 'https://api.commadotai.com')

class CommaApi:
  """comma API客户端类"""
  def __init__(self, token=None):
    self.session = requests.Session()
    # 设置User-agent
    self.session.headers['User-agent'] = 'OpenpilotTools'
    if token:
      # 如果提供了token,添加到请求头
      self.session.headers['Authorization'] = 'JWT ' + token

  def request(self, method, endpoint, **kwargs):
    """发送API请求
    
    Args:
      method: HTTP方法
      endpoint: API端点
      **kwargs: 请求参数
    Returns:
      响应的JSON数据
    Raises:
      UnauthorizedError: 认证失败
      APIError: API调用失败
    """
    with self.session.request(method, API_HOST + '/' + endpoint, **kwargs) as resp:
      resp_json = resp.json()
      if isinstance(resp_json, dict) and resp_json.get('error'):
        if resp.status_code in [401, 403]:
          raise UnauthorizedError('认证失败。请使用tools/lib/auth.py进行认证')

        e = APIError(str(resp.status_code) + ":" + resp_json.get('description', str(resp_json['error'])))
        e.status_code = resp.status_code
        raise e
      return resp_json

  def get(self, endpoint, **kwargs):
    """发送GET请求"""
    return self.request('GET', endpoint, **kwargs)

  def post(self, endpoint, **kwargs):
    """发送POST请求"""
    return self.request('POST', endpoint, **kwargs)

class APIError(Exception):
  """API调用异常"""
  pass

class UnauthorizedError(Exception):
  """认证失败异常"""
  pass
