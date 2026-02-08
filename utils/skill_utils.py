"""
技能工具：供 skills 调用的通用函数，封装为类方法便于统一引用。

技能字典推荐字段（便于 AI 精确识别与更好服务）：
- name, description, prompt, keywords：基础
- call_function, function_name, function_params, return_result：函数调用
- return_result_usage：函数返回值的用法（"none"|"prompt_suffix"|"prompt_placeholder"）
- time_range：时段限制
- priority：随机权重，越大越易被抽到
- intent_description：简短意图描述，供意图匹配
- negative_keywords：出现则不触发
- output_format：展示形式（"bubble"|"chat"）
- max_length：回复字数上限
"""
import random
import copy
from typing import Any, List, Dict, Union, Optional


class SkillUtils:
    """技能工具类，提供 skills 所需的可调用函数。"""

    @staticmethod
    def random_pick(source: Union[List[Any], Dict[Any, Any]]) -> Any:
        """
        从列表或字典中随机抽取一个值并返回。

        - 传入 list：等价于 random.choice(source)，返回其中一个元素。
        - 传入 dict：随机取一个 value 返回（不返回 key）。

        Args:
            source: 列表或字典，不可为空。

        Returns:
            随机到的那个元素（list 的元素或 dict 的某个 value）。

        Raises:
            ValueError: 当 source 为空或不是 list/dict 时。
        """
        if isinstance(source, list):
            if not source:
                raise ValueError("random_pick: list 不能为空")
            return random.choice(source)
        if isinstance(source, dict):
            if not source:
                raise ValueError("random_pick: dict 不能为空")
            return random.choice(list(source.values()))
        raise ValueError("random_pick: 只支持 list 或 dict，当前类型为 {}".format(type(source).__name__))

    @staticmethod
    def _resolve_param_value(val: Any, skill: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Any:
        """解析单个参数：若为以 $ 开头的字符串则从 skill/context 取值，否则原样返回。"""
        if not isinstance(val, str) or not val.startswith("$"):
            return val
        key = val[1:].strip()
        if not key:
            return val
        if key.startswith("context."):
            k = key[8:]
            return (context or {}).get(k) if context is not None else val
        if key.startswith("skill."):
            k = key[6:]
            return skill.get(k) if isinstance(skill, dict) else val
        return skill.get(key, val) if isinstance(skill, dict) else val

    @staticmethod
    def _resolve_params(params: Any, skill: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Any:
        """递归解析 function_params 中的 $ 占位符。"""
        if params is None:
            return None
        if isinstance(params, str) and params.startswith("$"):
            return SkillUtils._resolve_param_value(params, skill, context)
        if isinstance(params, dict):
            return {k: SkillUtils._resolve_params(v, skill, context) for k, v in params.items()}
        if isinstance(params, list):
            return [SkillUtils._resolve_params(v, skill, context) for v in params]
        return params

    @staticmethod
    def _get_callable(func_name: str):
        """根据函数名字符串解析可调用对象，支持 SkillUtils.xxx。"""
        name = (func_name or "").strip()
        if not name:
            return None
        parts = name.split(".")
        if len(parts) == 2 and parts[0] == "SkillUtils":
            return getattr(SkillUtils, parts[1], None)
        return None

    @staticmethod
    def execute_skill(
        skill: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行技能：根据技能配置决定是否调用函数，解析参数占位符，返回结构化结果。

        - 若 call_function 为 true 且 function_name 非空：解析 function_params（支持 $keywords、
          $context.xxx、$skill.xxx 占位符），调用函数，返回 { success, function_result, return_result_usage, error }。
        - 否则返回 { success: True, function_result: None, return_result_usage: "none", error: None }。

        Args:
            skill: 技能配置字典（如 auto_interaction_skill.json 中单条），需含 call_function、
                  function_name、function_params、return_result 等。
            context: 可选上下文，供参数占位符使用，如 {"user_message": "...", "current_hour": 9,
                    "assistant_state": "happy", "locale": "zh"}，便于函数或下游用「当前用户话术/时间/状态」做个性化。

        Returns:
            {
                "success": bool,
                "function_result": Any,   # 函数返回值，可能非字符串
                "return_result_usage": str,  # 来自 skill 的 return_result_usage 或 "none"
                "error": Optional[str],
            }
        """
        empty_result = {
            "success": True,
            "function_result": None,
            "return_result_usage": skill.get("return_result_usage", "none") if isinstance(skill, dict) else "none",
            "error": None,
        }
        if not isinstance(skill, dict):
            return {**empty_result, "success": False, "error": "skill 非字典"}
        if not skill.get("call_function") or not skill.get("function_name"):
            return empty_result
        name = (skill.get("function_name") or "").strip()
        if not name:
            return empty_result
        func = SkillUtils._get_callable(name)
        if not callable(func):
            return {**empty_result, "success": False, "error": "未找到可调用: {}".format(name)}
        raw_params = skill.get("function_params")
        params = SkillUtils._resolve_params(copy.deepcopy(raw_params), skill, context)
        return_result_usage = skill.get("return_result_usage", "none")
        if not isinstance(return_result_usage, str):
            return_result_usage = "none"
        try:
            if params is None:
                result = func()
            elif isinstance(params, dict):
                result = func(**params)
            elif isinstance(params, list):
                result = func(*params)
            else:
                result = func()
        except Exception as e:
            return {
                **empty_result,
                "success": False,
                "function_result": None,
                "return_result_usage": return_result_usage,
                "error": str(e),
            }
        return {
            "success": True,
            "function_result": result,
            "return_result_usage": return_result_usage,
            "error": None,
        }

    @staticmethod
    def build_prompt_with_result(
        base_prompt: str,
        exec_result: Dict[str, Any],
        placeholder: str = "{function_result}",
    ) -> str:
        """
        根据 execute_skill 的返回结果，将 function_result 注入到 prompt 中。

        - return_result_usage 为 "prompt_suffix" 时：在 base_prompt 末尾追加「建议/参考：{result}」。
        - 为 "prompt_placeholder" 时：用 str(function_result) 替换 base_prompt 中的 placeholder。
        - 为 "none" 或其它：返回原 base_prompt。

        Args:
            base_prompt: 原始技能 prompt 或拼接好的提示。
            exec_result: execute_skill 的返回值。
            placeholder: 占位符，仅 prompt_placeholder 时使用。

        Returns:
            注入后的 prompt 字符串。
        """
        base = base_prompt or ""
        if not exec_result.get("success") or exec_result.get("function_result") is None:
            if placeholder in base:
                base = base.replace(placeholder, "（随机主题）")
            return base
        usage = exec_result.get("return_result_usage") or "none"
        result = exec_result.get("function_result")
        if usage == "prompt_suffix":
            suffix = "建议或参考：{}".format(result)
            return base.strip() + "\n\n" + suffix
        if usage == "prompt_placeholder":
            return base.replace(placeholder, str(result))
        return base
