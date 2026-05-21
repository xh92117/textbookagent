# encoding:utf-8

import copy
import json
import logging
import os

from common.log import logger

# 灏嗘墍鏈夊彲鐢ㄧ殑閰嶇疆椤瑰啓鍦ㄥ瓧鍏搁噷, 璇蜂娇鐢ㄥ皬鍐欏瓧姣?
# 姝ゅ鐨勯厤缃€兼棤瀹為檯鎰忎箟锛岀▼搴忎笉浼氳鍙栨澶勭殑閰嶇疆锛屼粎鐢ㄤ簬鎻愮ず鏍煎紡锛岃灏嗛厤缃姞鍏ュ埌config.json涓?
available_setting = {
    # openai api閰嶇疆
    "open_ai_api_key": "",  # openai api key
    # openai apibase锛屽綋use_azure_chatgpt涓簍rue鏃讹紝闇€瑕佽缃搴旂殑api base
    "open_ai_api_base": "https://api.openai.com/v1",
    "claude_api_base": "https://api.anthropic.com/v1",  # claude api base
    "gemini_api_base": "https://generativelanguage.googleapis.com",  # gemini api base
    "custom_api_key": "",  # custom OpenAI-compatible provider api key (used when bot_type is "custom")
    "custom_api_base": "",  # custom OpenAI-compatible provider api base (used when bot_type is "custom")
    "proxy": "",  # openai浣跨敤鐨勪唬鐞?
    # chatgpt妯″瀷锛?褰搖se_azure_chatgpt涓簍rue鏃讹紝鍏跺悕绉颁负Azure涓妋odel deployment鍚嶇О
    "model": "gpt-3.5-turbo",  # 鍙€夋嫨: gpt-4o, pt-4o-mini, gpt-4-turbo, claude-3-sonnet, wenxin, moonshot, qwen-turbo, xunfei, glm-4, minimax, gemini绛夋ā鍨嬶紝鍏ㄩ儴鍙€夋ā鍨嬭瑙乧ommon/const.py鏂囦欢
    "bot_type": "",  # 鍙€夐厤缃紝浣跨敤鍏煎openai鏍煎紡鐨勪笁鏂规湇鍔℃椂鍊欙紝闇€濉?openai"鎴?custom"锛坈ustom妯″紡涓嬪垏鎹㈡ā鍨嬩笉浼氳嚜鍔ㄥ垏鎹ot_type锛夈€俠ot鍏蜂綋鍚嶇О璇﹁common/const.py鏂囦欢锛屽涓嶅～鏍规嵁model鍚嶇О鍒ゆ柇
    "review_model": "",  # 鏁欐潗瀹℃煡妯″瀷锛涗负绌烘椂娌跨敤 model
    "review_bot_type": "",  # 鏁欐潗瀹℃煡妯″瀷渚涘簲鍟嗭紱涓虹┖鏃舵部鐢?bot_type
    "image_model": "",  # 鍥剧墖鐢熸垚妯″瀷锛涗粠 ai_chat_models 涓€夋嫨
    "image_bot_type": "",  # 鍥剧墖鐢熸垚妯″瀷渚涘簲鍟?
    "knowledge_model": "",  # 鐭ヨ瘑搴撴瀯寤?LLM-WIKI 鏁寸悊妯″瀷锛涗粠 ai_chat_models 涓€夋嫨
    "knowledge_bot_type": "",  # 鐭ヨ瘑搴撴瀯寤?LLM-WIKI 鏁寸悊妯″瀷渚涘簲鍟?
    "knowledge_api_key": "",  # 鐭ヨ瘑搴撴瀯寤烘ā鍨嬩娇鐢?custom 璺敱鏃剁殑 API Key
    "knowledge_api_base": "",  # 鐭ヨ瘑搴撴瀯寤烘ā鍨嬩娇鐢?custom 璺敱鏃剁殑 API Base
    "ai_chat_models": [],  # AI 瀵硅瘽妯″瀷姹狅細[{id,name,provider,model,api_base}]锛孉PI Key 浣跨敤渚涘簲鍟嗙骇閰嶇疆
    "active_chat_model_id": "",  # 褰撳墠 AI 瀵硅瘽妯″瀷 id
    "textbooks_storage_dir": "",  # Optional textbook library root containing textbook id folders; default: <active_workspace>/textbooks
    "review_model_id": "",  # 瀹℃煡妯″瀷 id锛屽紩鐢?ai_chat_models
    "image_model_id": "",  # 鍥剧墖鐢熸垚妯″瀷 id锛屽紩鐢?ai_chat_models
    "knowledge_model_id": "",  # 鐭ヨ瘑搴撴瀯寤烘ā鍨?id锛屽紩鐢?ai_chat_models
    "use_azure_chatgpt": False,  # 鏄惁浣跨敤azure鐨刢hatgpt
    "azure_deployment_id": "",  # azure 妯″瀷閮ㄧ讲鍚嶇О
    "azure_api_version": "",  # azure api鐗堟湰
    # Bot瑙﹀彂閰嶇疆
    "single_chat_prefix": ["bot", "@bot"],  # 绉佽亰鏃舵枃鏈渶瑕佸寘鍚鍓嶇紑鎵嶈兘瑙﹀彂鏈哄櫒浜哄洖澶?
    "single_chat_reply_prefix": "[bot] ",  # 绉佽亰鏃惰嚜鍔ㄥ洖澶嶇殑鍓嶇紑锛岀敤浜庡尯鍒嗙湡浜?
    "single_chat_reply_suffix": "",  # 绉佽亰鏃惰嚜鍔ㄥ洖澶嶇殑鍚庣紑锛孿n 鍙互鎹㈣
    "group_chat_prefix": ["@bot"],  # 缇よ亰鏃跺寘鍚鍓嶇紑鍒欎細瑙﹀彂鏈哄櫒浜哄洖澶?
    "no_need_at": False,  # 缇よ亰鍥炲鏃舵槸鍚︿笉闇€瑕佽壘鐗?
    "group_chat_reply_prefix": "",  # 缇よ亰鏃惰嚜鍔ㄥ洖澶嶇殑鍓嶇紑
    "group_chat_reply_suffix": "",  # 缇よ亰鏃惰嚜鍔ㄥ洖澶嶇殑鍚庣紑锛孿n 鍙互鎹㈣
    "group_chat_keyword": [],  # 缇よ亰鏃跺寘鍚鍏抽敭璇嶅垯浼氳Е鍙戞満鍣ㄤ汉鍥炲
    "group_at_off": False,  # 鏄惁鍏抽棴缇よ亰鏃禓bot鐨勮Е鍙?
    "group_name_white_list": ["ChatGPT测试群", "ChatGPT测试群2"],  # 开启自动回复的群名称白名单
    "group_name_keyword_white_list": [],  # 寮€鍚嚜鍔ㄥ洖澶嶇殑缇ゅ悕绉板叧閿瘝鍒楄〃
    "group_chat_in_one_session": ["ChatGPT测试群"],  # 支持会话上下文共享的群名称
    "group_shared_session": False,  # 缇よ亰鏄惁鍏变韩浼氳瘽涓婁笅鏂囷紙鎵€鏈夋垚鍛樺叡浜級銆侳alse鏃舵瘡涓敤鎴峰湪缇ゅ唴鏈夌嫭绔嬩細璇?
    "nick_name_black_list": [],  # 鐢ㄦ埛鏄电О榛戝悕鍗?
    "group_welcome_msg": "",  # 閰嶇疆鏂颁汉杩涚兢鍥哄畾娆㈣繋璇紝涓嶉厤缃垯浣跨敤闅忔満椋庢牸娆㈣繋
    "trigger_by_self": False,  # 鏄惁鍏佽鏈哄櫒浜鸿Е鍙?
    "text_to_image": "dall-e-2",  # 鍥剧墖鐢熸垚妯″瀷锛屽彲閫?dall-e-2, dall-e-3
    # Azure OpenAI dall-e-3 閰嶇疆
    "dalle3_image_style": "vivid", # 鍥剧墖鐢熸垚dalle3鐨勯鏍硷紝鍙€夋湁 vivid, natural
    "dalle3_image_quality": "hd", # 鍥剧墖鐢熸垚dalle3鐨勮川閲忥紝鍙€夋湁 standard, hd
    # Azure OpenAI DALL-E API 閰嶇疆, 褰搖se_azure_chatgpt涓簍rue鏃?鐢ㄤ簬灏嗘枃瀛楀洖澶嶇殑璧勬簮鍜孌all-E鐨勮祫婧愬垎寮€.
    "azure_openai_dalle_api_base": "", # [鍙€塢 azure openai 鐢ㄤ簬鍥炲鍥剧墖鐨勮祫婧?endpoint锛岄粯璁や娇鐢?open_ai_api_base
    "azure_openai_dalle_api_key": "", # [鍙€塢 azure openai 鐢ㄤ簬鍥炲鍥剧墖鐨勮祫婧?key锛岄粯璁や娇鐢?open_ai_api_key
    "azure_openai_dalle_deployment_id":"", # [鍙€塢 azure openai 鐢ㄤ簬鍥炲鍥剧墖鐨勮祫婧?deployment id锛岄粯璁や娇鐢?text_to_image
    "image_proxy": True,  # 鏄惁闇€瑕佸浘鐗囦唬鐞嗭紝鍥藉唴璁块棶LinkAI鏃堕渶瑕?
    "image_create_prefix": ["画", "看", "找"],  # 开启图片回复的前缀
    "concurrency_in_session": 1,  # 鍚屼竴浼氳瘽鏈€澶氭湁澶氬皯鏉℃秷鎭湪澶勭悊涓紝澶т簬1鍙兘涔卞簭
    "image_create_size": "256x256",  # 鍥剧墖澶у皬,鍙€夋湁 256x256, 512x512, 1024x1024 (dall-e-3榛樿涓?024x1024)
    "group_chat_exit_group": False,
    # chatgpt浼氳瘽鍙傛暟
    "expires_in_seconds": 3600,  # 鏃犳搷浣滀細璇濈殑杩囨湡鏃堕棿
    # 浜烘牸鎻忚堪
    "character_desc": "你是ChatGPT，一个由OpenAI训练的大型语言模型，你在回答并解决人们的问题，并且可以使用多种语言与人交流。",
    "conversation_max_tokens": 1000,  # 鏀寔涓婁笅鏂囪蹇嗙殑鏈€澶氬瓧绗︽暟
    # chatgpt闄愭祦閰嶇疆
    "rate_limit_chatgpt": 20,  # chatgpt鐨勮皟鐢ㄩ鐜囬檺鍒?
    "rate_limit_dalle": 50,  # openai dalle鐨勮皟鐢ㄩ鐜囬檺鍒?
    # chatgpt api鍙傛暟 鍙傝€僪ttps://platform.openai.com/docs/api-reference/chat/create
    "temperature": 0.9,
    "top_p": 1,
    "frequency_penalty": 0,
    "presence_penalty": 0,
    "request_timeout": 180,  # chatgpt璇锋眰瓒呮椂鏃堕棿锛宱penai鎺ュ彛榛樿璁剧疆涓?00锛屽浜庨毦闂涓€鑸渶瑕佽緝闀挎椂闂?
    "agent_stream_idle_timeout": 30,  # Agent streaming: stop waiting when provider is idle after useful deltas
    "agent_stream_first_chunk_timeout": 180,  # Agent streaming: max wait before first model delta
    "knowledge_stream_idle_timeout": 30,  # Knowledge organize streaming: stop waiting when provider is idle after useful deltas
    "knowledge_stream_first_chunk_timeout": 180,  # Knowledge organize streaming: max wait before first model delta
    "timeout": 120,  # chatgpt閲嶈瘯瓒呮椂鏃堕棿锛屽湪杩欎釜鏃堕棿鍐咃紝灏嗕細鑷姩閲嶈瘯
    # Baidu 鏂囧績涓€瑷€鍙傛暟
    "baidu_wenxin_model": "eb-instant",  # 榛樿浣跨敤ERNIE-Bot-turbo妯″瀷
    "baidu_wenxin_api_key": "",  # Baidu api key
    "baidu_wenxin_secret_key": "",  # Baidu secret key
    "baidu_wenxin_prompt_enabled": False,  # Enable prompt if you are using ernie character model
    # Baidu Qianfan / ERNIE OpenAI-compatible API
    "qianfan_api_key": "",  # Baidu Qianfan API key in bce-v3 format
    "qianfan_api_base": "https://qianfan.baidubce.com/v2",  # Qianfan OpenAI-compatible API base
    # 璁鏄熺伀API
    "xunfei_app_id": "",  # 璁搴旂敤ID
    "xunfei_api_key": "",  # 璁 API key
    "xunfei_api_secret": "",  # 璁 API secret
    "xunfei_domain": "",  # 璁妯″瀷瀵瑰簲鐨刣omain鍙傛暟锛孲park4.0 Ultra涓?4.0Ultra锛屽叾浠栨ā鍨嬭瑙? https://www.xfyun.cn/doc/spark/Web.html
    "xunfei_spark_url": "",  # 璁妯″瀷瀵瑰簲鐨勮姹傚湴鍧€锛孲park4.0 Ultra涓?wss://spark-api.xf-yun.com/v4.0/chat锛屽叾浠栨ā鍨嬪弬鑰冭瑙? https://www.xfyun.cn/doc/spark/Web.html
    # claude 閰嶇疆
    "claude_api_cookie": "",
    "claude_uuid": "",
    # claude api key
    "claude_api_key": "",
    # 閫氫箟鍗冮棶API, 鑾峰彇鏂瑰紡鏌ョ湅鏂囨。 https://help.aliyun.com/document_detail/2587494.html
    "qwen_access_key_id": "",
    "qwen_access_key_secret": "",
    "qwen_agent_key": "",
    "qwen_app_id": "",
    "qwen_node_id": "",  # 娴佺▼缂栨帓妯″瀷鐢ㄥ埌鐨刬d锛屽鏋滄病鏈夌敤鍒皅wen_node_id锛岃鍔″繀淇濇寔涓虹┖瀛楃涓?
    # 闃块噷鐏电Н(閫氫箟鏂扮増sdk)妯″瀷api key
    "dashscope_api_key": "",
    "dashscope_api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    # Google Gemini Api Key
    "gemini_api_key": "",
    # 璇煶璁剧疆
    "speech_recognition": True,  # 鏄惁寮€鍚闊宠瘑鍒?
    "group_speech_recognition": False,  # 鏄惁寮€鍚兢缁勮闊宠瘑鍒?
    "voice_reply_voice": False,  # 鏄惁浣跨敤璇煶鍥炲璇煶锛岄渶瑕佽缃搴旇闊冲悎鎴愬紩鎿庣殑api key
    "always_reply_voice": False,  # 鏄惁涓€鐩翠娇鐢ㄨ闊冲洖澶?
    "voice_to_text": "openai",  # 璇煶璇嗗埆寮曟搸锛屾敮鎸乷penai,baidu,google,azure,xunfei,ali
    "text_to_voice": "openai",  # 璇煶鍚堟垚寮曟搸锛屾敮鎸乷penai,baidu,google,azure,xunfei,ali,pytts(offline),elevenlabs,edge(online)
    "text_to_voice_model": "tts-1",
    "tts_voice_id": "alloy",
    # baidu 璇煶api閰嶇疆锛?浣跨敤鐧惧害璇煶璇嗗埆鍜岃闊冲悎鎴愭椂闇€瑕?
    "baidu_app_id": "",
    "baidu_api_key": "",
    "baidu_secret_key": "",
    # 1536鏅€氳瘽(鏀寔绠€鍗曠殑鑻辨枃璇嗗埆) 1737鑻辫 1637绮よ 1837鍥涘窛璇?1936鏅€氳瘽杩滃満
    "baidu_dev_pid": 1536,
    # azure 璇煶api閰嶇疆锛?浣跨敤azure璇煶璇嗗埆鍜岃闊冲悎鎴愭椂闇€瑕?
    "azure_voice_api_key": "",
    "azure_voice_region": "japaneast",
    # elevenlabs 璇煶api閰嶇疆
    "xi_api_key": "",  # 鑾峰彇ap鐨勬柟娉曞彲浠ュ弬鑰僪ttps://docs.elevenlabs.io/api-reference/quick-start/authentication
    "xi_voice_id": "",  # ElevenLabs鎻愪緵浜?绉嶈嫳寮忋€佺編寮忕瓑鑻辫鍙戦煶id锛屽垎鍒槸鈥淎dam/Antoni/Arnold/Bella/Domi/Elli/Josh/Rachel/Sam鈥?
    # 鏈嶅姟鏃堕棿闄愬埗
    "chat_time_module": False,  # 鏄惁寮€鍚湇鍔℃椂闂撮檺鍒?
    "chat_start_time": "00:00",  # 鏈嶅姟寮€濮嬫椂闂?
    "chat_stop_time": "24:00",  # 鏈嶅姟缁撴潫鏃堕棿
    # 缈昏瘧api
    "translate": "baidu",  # 缈昏瘧api锛屾敮鎸乥aidu, youdao
    # baidu缈昏瘧api鐨勯厤缃?
    "baidu_translate_app_id": "",  # 鐧惧害缈昏瘧api鐨刟ppid
    "baidu_translate_app_key": "",  # 鐧惧害缈昏瘧api鐨勭閽?
    # youdao缈昏瘧api鐨勯厤缃?
    "youdao_translate_app_key": "",  # 鏈夐亾缈昏瘧api鐨勫簲鐢↖D
    "youdao_translate_app_secret": "",  # 鏈夐亾缈昏瘧api鐨勫簲鐢ㄥ瘑閽?
    # wechatmp鐨勯厤缃?
    "wechatmp_token": "",  # 寰俊鍏紬骞冲彴鐨凾oken
    "wechatmp_port": 8080,  # 寰俊鍏紬骞冲彴鐨勭鍙?闇€瑕佺鍙ｈ浆鍙戝埌80鎴?43
    "wechatmp_app_id": "",  # 寰俊鍏紬骞冲彴鐨刟ppID
    "wechatmp_app_secret": "",  # 寰俊鍏紬骞冲彴鐨刟ppsecret
    "wechatmp_aes_key": "",  # 寰俊鍏紬骞冲彴鐨凟ncodingAESKey锛屽姞瀵嗘ā寮忛渶瑕?
    # wechatcom鐨勯€氱敤閰嶇疆
    "wechatcom_corp_id": "",  # 浼佷笟寰俊鍏徃鐨刢orpID
    # wechatcomapp鐨勯厤缃?
    "wechatcomapp_token": "",  # 浼佷笟寰俊app鐨則oken
    "wechatcomapp_port": 9898,  # 浼佷笟寰俊app鐨勬湇鍔＄鍙?涓嶉渶瑕佺鍙ｈ浆鍙?
    "wechatcomapp_secret": "",  # 浼佷笟寰俊app鐨剆ecret
    "wechatcomapp_agent_id": "",  # 浼佷笟寰俊app鐨刟gent_id
    "wechatcomapp_aes_key": "",  # 浼佷笟寰俊app鐨刟es_key
    # 椋炰功閰嶇疆
    "feishu_port": 80,  # 椋炰功bot鐩戝惉绔彛锛屼粎webhook妯″紡闇€瑕?
    "feishu_app_id": "",  # 椋炰功鏈哄櫒浜哄簲鐢ˋPP Id
    "feishu_app_secret": "",  # 椋炰功鏈哄櫒浜篈PP secret
    "feishu_token": "",  # 椋炰功 verification token锛屼粎webhook妯″紡闇€瑕?
    "feishu_event_mode": "websocket",  # 椋炰功浜嬩欢鎺ユ敹妯″紡: webhook(HTTP鏈嶅姟鍣? 鎴?websocket(闀胯繛鎺?
    # 椋炰功娴佸紡鍥炲锛堝熀浜庡畼鏂?cardkit 娴佸紡鍗＄墖 API锛岄渶瑕佹満鍣ㄤ汉寮€閫?cardkit:card:write 鏉冮檺锛屼笖椋炰功瀹㈡埛绔?7.20+锛?
    "feishu_stream_reply": True,  # 鏄惁寮€鍚祦寮忓洖澶嶏紙鎵撳瓧鏈烘晥鏋滐級銆傚け璐?鑰佸鎴风鑷姩闄嶇骇涓洪潪娴佸紡鎴栧崌绾ф彁绀?
    # 閽夐拤閰嶇疆
    "dingtalk_client_id": "",  # 閽夐拤鏈哄櫒浜篊lient ID 
    "dingtalk_client_secret": "",  # 閽夐拤鏈哄櫒浜篊lient Secret
    "dingtalk_card_enabled": False,
    # 浼佸井鏅鸿兘鏈哄櫒浜洪厤缃?闀胯繛鎺ユā寮?
    "wecom_bot_id": "",  # 浼佸井鏅鸿兘鏈哄櫒浜築otID
    "wecom_bot_secret": "",  # 浼佸井鏅鸿兘鏈哄櫒浜洪暱杩炴帴Secret
    # 寰俊閰嶇疆
    "weixin_token": "",  # 寰俊鐧诲綍鍚庤幏鍙栫殑bot_token锛岀暀绌哄垯鍚姩鏃惰嚜鍔ㄦ壂鐮佺櫥褰?
    "weixin_base_url": "https://ilinkai.weixin.qq.com",  # Weixin ilink API base URL
    "weixin_cdn_base_url": "https://novac2c.cdn.weixin.qq.com/c2c",  # CDN base URL
    "weixin_credentials_path": "~/.weixin_cow_credentials.json",  # credentials file path
    # chatgpt鎸囦护鑷畾涔夎Е鍙戣瘝
    "clear_memory_commands": ["#娓呴櫎璁板繂"],  # 閲嶇疆浼氳瘽鎸囦护锛屽繀椤讳互#寮€澶?
    # channel閰嶇疆
    "channel_type": "",  # 閫氶亾绫诲瀷锛屾敮鎸佸娓犻亾鍚屾椂杩愯銆傚崟涓? "feishu"锛屽涓? "feishu, dingtalk" 鎴?["feishu", "dingtalk"]銆傚彲閫夊€? web,feishu,dingtalk,wecom_bot,weixin,wechatmp,wechatmp_service,wechatcom_app
    "web_console": True,  # 鏄惁鑷姩鍚姩Web鎺у埗鍙帮紙榛樿鍚姩锛夈€傝涓篎alse鍙鐢?
    "subscribe_msg": "",  # 璁㈤槄娑堟伅, 鏀寔: wechatmp, wechatmp_service, wechatcom_app
    "debug": False,  # 鏄惁寮€鍚痙ebug妯″紡锛屽紑鍚悗浼氭墦鍗版洿澶氭棩蹇?
    "appdata_dir": "",  # 鏁版嵁鐩綍
    "system_workspace": "",  # 绯荤粺鍖烘牴鐩綍锛涗负绌烘椂娌跨敤 agent_workspace
    "active_workspace": "",  # 褰撳墠涓氬姟宸ヤ綔鍖猴紱涓虹┖鏃舵部鐢?agent_workspace
    "workspace_dir": "",  # active_workspace 鐨勫吋瀹瑰埆鍚?
    "workspace_split_enabled": True,  # 鏄惁灏嗙郴缁熸枃浠舵斁鍏?system/ 瀛愮洰褰?
    # 鎻掍欢閰嶇疆
    "plugin_trigger_prefix": "$",  # 瑙勮寖鎻掍欢鎻愪緵鑱婂ぉ鐩稿叧鎸囦护鐨勫墠缂€锛屽缓璁笉瑕佸拰绠＄悊鍛樻寚浠ゅ墠缂€"#"鍐茬獊
    # 鏄惁浣跨敤鍏ㄥ眬鎻掍欢閰嶇疆
    "use_global_plugin_config": False,
    "max_media_send_count": 3,  # 鍗曟鏈€澶у彂閫佸獟浣撹祫婧愮殑涓暟
    "media_send_interval": 1,  # 鍙戦€佸浘鐗囩殑浜嬩欢闂撮殧锛屽崟浣嶇
    # 鏅鸿氨AI 骞冲彴閰嶇疆
    "zhipu_ai_api_key": "",
    "zhipu_ai_api_base": "https://open.bigmodel.cn/api/paas/v4",
    "moonshot_api_key": "",
    "moonshot_base_url": "https://api.moonshot.cn/v1",
    # 璞嗗寘(鐏北鏂硅垷) 骞冲彴閰嶇疆
    "ark_api_key": "",
    "ark_base_url": "https://ark.cn-beijing.volces.com/api/v3",
    # 榄旀惌绀惧尯 骞冲彴閰嶇疆
    "modelscope_api_key": "",
    "modelscope_base_url": "https://api-inference.modelscope.cn/v1/chat/completions",
    # LinkAI骞冲彴閰嶇疆
    "use_linkai": False,
    "linkai_api_key": "",
    "linkai_app_code": "",
    "linkai_api_base": "https://api.link-ai.tech",
    "cloud_host": "client.link-ai.tech",
    "cloud_port": None,
    "cloud_deployment_id": "",
    "minimax_api_key": "",
    "Minimax_group_id": "",
    "Minimax_base_url": "",
    "deepseek_api_key": "",
    "deepseek_api_base": "https://api.deepseek.com/v1",
    "web_port": 9899,
    "web_host": "127.0.0.1",  # Bind host; use 0.0.0.0 only when remote access is intentional and protected
    "web_password": "",  # Web console password; empty means no authentication required
    "web_session_expire_days": 30,  # Auth session expiry in days
    "agent": True,  # 鏄惁寮€鍚疉gent妯″紡
    "agent_workspace": "~/textbook_workspace",  # agent宸ヤ綔绌洪棿璺緞锛岀敤浜庡瓨鍌╯kills銆乵emory绛?
    "agent_max_context_tokens": 50000,  # Agent模式下最大上下文tokens
    "agent_max_context_turns": 20,  # Agent模式下最大上下文记忆轮次
    "agent_model_context_window": 0,  # 显式覆盖当前模型上下文窗口；0表示自动识别
    "agent_context_reserve_tokens": 0,  # 显式覆盖输出/工具增长预留tokens；0表示自动计算
    "agent_max_steps": 20,  # Agent妯″紡涓嬪崟娆¤繍琛屾渶澶у喅绛栨鏁?
    "agent_stream_idle_timeout_seconds": 180,  # Close a stalled model stream after this many seconds without chunks; 0 disables
    "enable_thinking": False,  # Enable deep-thinking mode for thinking-capable models
    "reasoning_effort": "high",  # Reasoning depth under thinking mode: "high" or "max"
    "knowledge": True,  # 鏄惁寮€鍚煡璇嗗簱鍔熻兘
    "knowledge_organize_mode": "auto",  # Knowledge organize mode: auto, fast/local, or deep/llm/accurate
    "knowledge_fast_chunk_threshold": 20,  # Use local metadata when a source has more chunks than this in auto mode
    "knowledge_extract_assets": True,  # Extract useful images from PDF/DOCX into LLM-WIKI assets
    "knowledge_skip_logo_watermark_assets": True,  # Skip likely logos/watermarks when extracting document images
    "knowledge_min_asset_width": 120,  # Minimum extracted image width to keep
    "knowledge_min_asset_height": 120,  # Minimum extracted image height to keep
    "knowledge_min_asset_area": 20000,  # Minimum extracted image pixel area to keep
    "skill": {},  # Per-skill runtime config; nested keys flatten to SKILL_<NAME>_<KEY> env vars at startup
    "mcp_servers": [],  # MCP server list; each entry supports type "stdio" (local process) or "sse" (remote URL)
}


class Config(dict):
    def __init__(self, d=None):
        super().__init__()
        if d is None:
            d = {}
        for k, v in d.items():
            self[k] = v
        # user_datas: 鐢ㄦ埛鏁版嵁锛宬ey涓虹敤鎴峰悕锛寁alue涓虹敤鎴锋暟鎹紝涔熸槸dict
        self.user_datas = {}

    def __getitem__(self, key):
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        return super().__setitem__(key, value)

    def get(self, key, default=None):
        # 璺宠繃浠ヤ笅鍒掔嚎寮€澶寸殑娉ㄩ噴瀛楁
        if key.startswith("_"):
            return super().get(key, default)
        
        # 濡傛灉key涓嶅湪available_setting涓紝鐩存帴璧癲ict鐨刧et锛岃繑鍥瀋onfig.json涓疄闄呭姞杞界殑鍊硷紙濡備笉瀛樺湪鍒欒繑鍥瀌efault锛?
        if key not in available_setting:
            return super().get(key, default)
        
        try:
            return self[key]
        except KeyError as e:
            return default
        except Exception as e:
            raise e

    # Make sure to return a dictionary to ensure atomic
    def get_user_data(self, user) -> dict:
        if self.user_datas.get(user) is None:
            self.user_datas[user] = {}
        return self.user_datas[user]

    def load_user_datas(self):
        json_path = os.path.join(get_appdata_dir(), "user_datas.json")
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                self.user_datas = loaded if isinstance(loaded, dict) else {}
                logger.debug("[Config] User datas loaded.")
        except FileNotFoundError as e:
            logger.debug("[Config] User datas file not found, ignore.")
        except Exception as e:
            logger.warning("[Config] User datas error: {}".format(e))
            self.user_datas = {}

    def save_user_datas(self):
        try:
            with open(os.path.join(get_appdata_dir(), "user_datas.json"), "w", encoding="utf-8") as f:
                json.dump(self.user_datas, f, ensure_ascii=False, indent=2)
                logger.info("[Config] User datas saved.")
        except Exception as e:
            logger.info("[Config] User datas error: {}".format(e))


config = Config()


def drag_sensitive(config):
    try:
        if isinstance(config, str):
            conf_dict: dict = json.loads(config)
            conf_dict_copy = copy.deepcopy(conf_dict)
            for key in conf_dict_copy:
                if "key" in key or "secret" in key:
                    if isinstance(conf_dict_copy[key], str):
                        conf_dict_copy[key] = conf_dict_copy[key][0:3] + "*" * 5 + conf_dict_copy[key][-3:]
            return json.dumps(conf_dict_copy, indent=4)

        elif isinstance(config, dict):
            config_copy = copy.deepcopy(config)
            for key in config:
                if "key" in key or "secret" in key:
                    if isinstance(config_copy[key], str):
                        config_copy[key] = config_copy[key][0:3] + "*" * 5 + config_copy[key][-3:]
            return config_copy
    except Exception as e:
        logger.exception(e)
        return config
    return config


def load_config():
    global config

    # Print ASCII logo
    logger.info(" _____         _   _                 _      ___                    _   ")
    logger.info("|_   _|____  _| |_| |__   ___   ___ | | __ / _ \\  __ _  ___ _ __ | |_ ")
    logger.info("  | |/ _ \\ \\/ / __| '_ \\ / _ \\ / _ \\| |/ /| |_| |/ _` |/ _ \\ '_ \\| __|")
    logger.info("  | |  __/>  <| |_| |_) | (_) | (_) |   < |  _  | (_| |  __/ | | | |_ ")
    logger.info("  |_|\\___/_/\\_\\\\__|_.__/ \\___/ \\___/|_|\\_\\|_| |_|\\__, |\\___|_| |_|\\__|")
    logger.info("                                                   |___/               ")
    logger.info("")
    config_path = "./config.json"
    if not os.path.exists(config_path):
        logger.info("閰嶇疆鏂囦欢涓嶅瓨鍦紝灏嗕娇鐢╟onfig-template.json妯℃澘")
        config_path = "./config-template.json"

    config_str = read_file(config_path)
    logger.debug("[INIT] config str: {}".format(drag_sensitive(config_str)))

    # 灏唈son瀛楃涓插弽搴忓垪鍖栦负dict绫诲瀷
    config = Config(json.loads(config_str))

    # override config with environment variables.
    # Some online deployment platforms (e.g. Railway) deploy project from github directly. So you shouldn't put your secrets like api key in a config file, instead use environment variables to override the default config.
    for name, value in os.environ.items():
        name = name.lower()
        # 璺宠繃浠ヤ笅鍒掔嚎寮€澶寸殑娉ㄩ噴瀛楁
        if name.startswith("_"):
            continue
        if name in available_setting:
            logger.info("[INIT] override config by environ args: {}={}".format(name, value))
            config[name] = _parse_env_value(value)

    if config.get("debug", False):
        logger.setLevel(logging.DEBUG)
        logger.debug("[INIT] set log level to DEBUG")

    logger.info("[INIT] load config: {}".format(drag_sensitive(config)))

    # 鎵撳嵃绯荤粺鍒濆鍖栦俊鎭?
    logger.info("[INIT] ========================================")
    logger.info("[INIT] System Initialization")
    logger.info("[INIT] ========================================")
    logger.info("[INIT] Channel: {}".format(config.get("channel_type", "unknown")))
    logger.info("[INIT] Model: {}".format(config.get("model", "unknown")))

    # Agent妯″紡淇℃伅
    if config.get("agent", False):
        workspace = config.get("agent_workspace", "~/textbook_workspace")
        logger.info("[INIT] Mode: Agent (workspace: {})".format(workspace))
    else:
        logger.info("[INIT] Mode: Chat (鍦╟onfig.json涓缃?\"agent\":true 鍙惎鐢ˋgent妯″紡)")

    logger.info("[INIT] Debug: {}".format(config.get("debug", False)))
    logger.info("[INIT] ========================================")

    # Sync selected config values to environment variables so that
    # subprocesses (e.g. shell skill scripts) can access them directly.
    # Existing env vars are NOT overwritten (env takes precedence).
    _CONFIG_TO_ENV = {
        "open_ai_api_key": "OPENAI_API_KEY",
        "open_ai_api_base": "OPENAI_API_BASE",
        "linkai_api_key": "LINKAI_API_KEY",
        "linkai_api_base": "LINKAI_API_BASE",
        "claude_api_key": "CLAUDE_API_KEY",
        "claude_api_base": "CLAUDE_API_BASE",
        "gemini_api_key": "GEMINI_API_KEY",
        "gemini_api_base": "GEMINI_API_BASE",
        "minimax_api_key": "MINIMAX_API_KEY",
        "minimax_api_base": "MINIMAX_API_BASE",
        "deepseek_api_key": "DEEPSEEK_API_KEY",
        "deepseek_api_base": "DEEPSEEK_API_BASE",
        "qianfan_api_key": "QIANFAN_API_KEY",
        "qianfan_api_base": "QIANFAN_API_BASE",
        "zhipu_ai_api_key": "ZHIPU_AI_API_KEY",
        "zhipu_ai_api_base": "ZHIPU_AI_API_BASE",
        "moonshot_api_key": "MOONSHOT_API_KEY",
        "moonshot_api_base": "MOONSHOT_API_BASE",
        "ark_api_key": "ARK_API_KEY",
        "ark_api_base": "ARK_API_BASE",
        "dashscope_api_key": "DASHSCOPE_API_KEY",
        "dashscope_api_base": "DASHSCOPE_API_BASE",
        # Channel credentials (used by skills that check env vars)
        "feishu_app_id": "FEISHU_APP_ID",
        "feishu_app_secret": "FEISHU_APP_SECRET",
        "dingtalk_client_id": "DINGTALK_CLIENT_ID",
        "dingtalk_client_secret": "DINGTALK_CLIENT_SECRET",
        "wechatmp_app_id": "WECHATMP_APP_ID",
        "wechatmp_app_secret": "WECHATMP_APP_SECRET",
        "wechatcomapp_agent_id": "WECHATCOMAPP_AGENT_ID",
        "wechatcomapp_secret": "WECHATCOMAPP_SECRET",
        "qq_app_id": "QQ_APP_ID",
        "qq_app_secret": "QQ_APP_SECRET",
        "weixin_token": "WEIXIN_TOKEN",
    }
    injected = 0
    for conf_key, env_key in _CONFIG_TO_ENV.items():
        if env_key not in os.environ:
            val = config.get(conf_key, "")
            if val:
                os.environ[env_key] = str(val)
                injected += 1

    injected += _sync_skill_config_to_env(config.get("skill", {}))

    if injected:
        logger.info("[INIT] Synced {} config values to environment variables".format(injected))

    config.load_user_datas()


def _sync_skill_config_to_env(skill_section) -> int:
    """Flatten skill-namespaced config into environment variables.

    Mapping rule: ``config["skill"][<name>][<key>]`` -> ``SKILL_<NAME>_<KEY>``
    (e.g. ``skill["image-generation"].model`` -> ``SKILL_IMAGE_GENERATION_MODEL``).

    This lets subprocess-based skill scripts read their own settings without
    importing project code. Existing env vars are NOT overwritten so the
    real environment always wins.

    Returns the number of variables actually injected.
    """
    if not isinstance(skill_section, dict):
        return 0
    injected = 0
    for skill_name, skill_conf in skill_section.items():
        if not isinstance(skill_conf, dict):
            continue
        name_part = str(skill_name).replace("-", "_").upper()
        for key, val in skill_conf.items():
            if val is None or val == "":
                continue
            env_key = "SKILL_{}_{}".format(name_part, str(key).upper())
            if env_key in os.environ:
                continue
            os.environ[env_key] = str(val)
            injected += 1
    return injected


def get_root():
    return os.path.dirname(os.path.abspath(__file__))


def read_file(path):
    with open(path, mode="r", encoding="utf-8-sig") as f:
        return f.read()


def _parse_env_value(value: str):
    raw = str(value)
    lowered = raw.lower()
    if lowered == "false":
        return False
    if lowered == "true":
        return True
    if lowered == "null":
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


def conf():
    return config


def get_appdata_dir():
    configured = conf().get("appdata_dir", "")
    if configured:
        data_path = os.path.join(get_root(), configured)
    else:
        from common.app_paths import system_dir
        data_path = system_dir()
    if not os.path.exists(data_path):
        logger.info("[INIT] data path not exists, create it: {}".format(data_path))
        os.makedirs(data_path)
    return data_path


def subscribe_msg():
    trigger_prefix = conf().get("single_chat_prefix", [""])[0]
    msg = conf().get("subscribe_msg", "")
    return msg.format(trigger_prefix=trigger_prefix)


# global plugin config
plugin_config = {}


def write_plugin_config(pconf: dict):
    """
    鍐欏叆鎻掍欢鍏ㄥ眬閰嶇疆
    :param pconf: 鍏ㄩ噺鎻掍欢閰嶇疆
    """
    global plugin_config
    for k in pconf:
        plugin_config[k.lower()] = pconf[k]

def remove_plugin_config(name: str):
    """
    绉婚櫎寰呴噸鏂板姞杞界殑鎻掍欢鍏ㄥ眬閰嶇疆
    :param name: 寰呴噸杞界殑鎻掍欢鍚?
    """
    global plugin_config
    plugin_config.pop(name.lower(), None)


def pconf(plugin_name: str) -> dict:
    """
    鏍规嵁鎻掍欢鍚嶇О鑾峰彇閰嶇疆
    :param plugin_name: 鎻掍欢鍚嶇О
    :return: 璇ユ彃浠剁殑閰嶇疆椤?
    """
    return plugin_config.get(plugin_name.lower())


# 鍏ㄥ眬閰嶇疆锛岀敤浜庡瓨鏀惧叏灞€鐢熸晥鐨勭姸鎬?
global_config = {"admin_users": []}
