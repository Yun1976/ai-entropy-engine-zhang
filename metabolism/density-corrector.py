#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
the AI system信息密度校正模型
基于残差数列训练的 Ridge 回归校正器
"""

import json
import math
import statistics
from typing import Dict, List, Tuple, Optional

class DensityCorrector:
    """基于残差数列的密度校正器"""
    
    def __init__(self):
        self.coefficients: Dict[str, float] = {}
        self.intercept: float = 0.0
        self.r_squared: float = 0.0
        self.rmse: float = 0.0
        self.sample_count: int = 0
        
    @staticmethod
    def ridge_regression(X: List[List[float]], y: List[float], alpha: float = 1.0) -> Tuple[Dict[str, float], float, float]:
        """
        纯 Python 实现的 Ridge 回归
        X: 特征矩阵，y: 目标值，alpha: L2 正则化参数
        返回: (系数字典, 截距, 均方误差)
        """
        n_samples = len(X)
        n_features = len(X[0]) if n_samples > 0 else 0
        
        if n_samples == 0:
            return {}, 0.0, float('inf')
            
        # 添加截距项的偏置
        X_with_bias = [[1.0] + row for row in X]
        
        # 特征名称
        feature_names = ['intercept', 'S', 'lambda', 'R', 'C', 'rho', 'cycle']
        
        # 转置矩阵以便处理列
        X_matrix = list(zip(*X_with_bias))
        
        # 初始化系数
        coefficients = [0.0] * len(feature_names)
        
        # 梯度下降参数
        learning_rate = 0.01
        max_iterations = 1000
        
        for iteration in range(max_iterations):
            # 计算预测值
            predictions = [sum(coefficients[i] * X_matrix[i][j] for i in range(len(coefficients))) 
                          for j in range(n_samples)]
            
            # 计算误差
            errors = [predictions[j] - y[j] for j in range(n_samples)]
            
            # 计算梯度
            gradients = []
            for i in range(len(coefficients)):
                if i == 0:  # 截距项
                    gradient = sum(errors[j] / n_samples for j in range(n_samples))
                else:  # 特征项（含L2正则化）
                    gradient = (sum(errors[j] * X_matrix[i][j] for j in range(n_samples)) / n_samples +
                              alpha * coefficients[i])
                gradients.append(gradient)
            
            # 更新系数
            old_coefficients = coefficients.copy()
            for i in range(len(coefficients)):
                coefficients[i] -= learning_rate * gradients[i]
            
            # 检查收敛
            coefficient_change = sum((coefficients[i] - old_coefficients[i])**2 for i in range(len(coefficients)))
            if coefficient_change < 1e-6:
                break
        
        # 计算均方误差
        mse = sum(errors[j]**2 for j in range(n_samples)) / n_samples
        rmse = math.sqrt(mse)
        
        # 计算R²
        y_mean = sum(y) / n_samples
        total_sum_of_squares = sum((yj - y_mean)**2 for yj in y)
        explained_sum_of_squares = sum((predictions[j] - y_mean)**2 for j in range(n_samples))
        r_squared = explained_sum_of_squares / total_sum_of_squares if total_sum_of_squares > 0 else 0.0
        
        # 返回系数字典和指标
        coeff_dict = {feature_names[i]: coefficients[i] for i in range(len(feature_names))}
        return coeff_dict, coefficients[0], rmse  # coefficients[0] 是截距
    
    def train(self, data: List[Dict], sample_size: Optional[int] = None) -> bool:
        """
        训练模型
        data: 残差数据列表，每个元素是包含特征和residual字段的字典
        sample_size: 使用的样本数量，None表示全部
        """
        # 过滤已验证的数据
        validated_data = [d for d in data if d.get('residual') is not None and d.get('validation_status') == 'validated']
        
        if len(validated_data) < 100:
            print(f"训练失败：需要至少100条已验证样本，当前只有{len(validated_data)}条")
            return False
            
        if sample_size and sample_size < len(validated_data):
            validated_data = validated_data[-sample_size:]
        
        # 提取特征和目标
        X = []
        y = []
        
        for record in validated_data:
            features = [
                record.get('S', 0.0),
                record.get('lambda', 1.0),
                record.get('R', 0.0),
                record.get('C', 0.0),
                record.get('rho_estimated', 0.0),
                record.get('cycle', 1)
            ]
            X.append(features)
            y.append(record['residual'])
        
        # 训练 Ridge 回归
        alpha = 1.0  # L2正则化参数
        self.coefficients, self.intercept, self.rmse = self.ridge_regression(X, y, alpha)
        self.r_squared = self.calculate_r_squared(X, y)
        self.sample_count = len(validated_data)
        
        return True
    
    def calculate_r_squared(self, X: List[List[float]], y: List[float]) -> float:
        """计算R²分数"""
        y_mean = sum(y) / len(y)
        total_sum_squares = sum((yi - y_mean)**2 for yi in y)
        
        predictions = []
        for i, features in enumerate(X):
            # 添加截距
            prediction = self.intercept + sum(self.coefficients[f] * features[j] 
                                             for j, f in enumerate(['S', 'lambda', 'R', 'C', 'rho_estimated', 'cycle']))
            predictions.append(prediction)
        
        explained_sum_squares = sum((predictions[i] - y_mean)**2 for i in range(len(y)))
        return explained_sum_squares / total_sum_squares if total_sum_squares > 0 else 0.0
    
    def predict_correction(self, S: float, lambda_val: float, R: float, C: float, rho: float, cycle: int) -> float:
        """预测残差校正"""
        features = [S, lambda_val, R, C, rho, cycle]
        correction = self.intercept
        for i, feature_name in enumerate(['S', 'lambda', 'R', 'C', 'rho_estimated', 'cycle']):
            if feature_name in self.coefficients:
                correction += self.coefficients[feature_name] * features[i]
        return correction
    
    def get_corrected_density(self, S: float, lambda_val: float, R: float, C: float, rho: float, cycle: int) -> float:
        """获取校正后的密度"""
        correction = self.predict_correction(S, lambda_val, R, C, rho, cycle)
        corrected_rho = rho + correction
        
        # 只在 |correction| > 0.1 时应用校正
        if abs(correction) > 0.1:
            return corrected_rho
        else:
            return rho
    
    def save_model(self, filepath: str):
        """保存模型"""
        model_data = {
            'coefficients': self.coefficients,
            'intercept': self.intercept,
            'r_squared': self.r_squared,
            'rmse': self.rmse,
            'sample_count': self.sample_count,
            'training_timestamp': json.dumps({'iso8601': 'now'})
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(model_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load_model(cls, filepath: str) -> 'DensityCorrector':
        """加载模型"""
        with open(filepath, 'r', encoding='utf-8') as f:
            model_data = json.load(f)
        
        corrector = cls()
        corrector.coefficients = model_data['coefficients']
        corrector.intercept = model_data['intercept']
        corrector.r_squared = model_data['r_squared']
        corrector.rmse = model_data['rmse']
        corrector.sample_count = model_data['sample_count']
        
        return corrector

def load_residual_data(filepath: str) -> List[Dict]:
    """加载残差数据"""
    data = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    data.append(json.loads(line))
    except FileNotFoundError:
        print(f"文件 {filepath} 不存在")
    except Exception as e:
        print(f"加载数据时出错: {e}")
    
    return data

def time_series_cv(data: List[Dict], n_folds: int = 5) -> Dict[str, float]:
    """时间序列交叉验证"""
    if len(data) < n_folds:
        return {'rmse': float('inf'), 'r_squared': 0.0}
    
    # 按cycle排序
    sorted_data = sorted(data, key=lambda x: x.get('cycle', 1))
    
    fold_size = len(sorted_data) // n_folds
    cv_scores = []
    
    for fold in range(n_folds):
        train_data = sorted_data[:fold*fold_size] + sorted_data[(fold+1)*fold_size:]
        test_data = sorted_data[fold*fold_size:(fold+1)*fold_size]
        
        # 过滤已验证的数据
        train_validated = [d for d in train_data if d.get('residual') is not None and d.get('validation_status') == 'validated']
        test_validated = [d for d in test_data if d.get('residual') is not None and d.get('validation_status') == 'validated']
        
        if len(train_validated) < 10 or len(test_validated) < 5:
            continue
        
        # 提取特征
        X_train = []
        y_train = []
        for record in train_validated:
            X_train.append([
                record.get('S', 0.0),
                record.get('lambda', 1.0),
                record.get('R', 0.0),
                record.get('C', 0.0),
                record.get('rho_estimated', 0.0),
                record.get('cycle', 1)
            ])
            y_train.append(record['residual'])
        
        X_test = []
        y_test = []
        for record in test_validated:
            X_test.append([
                record.get('S', 0.0),
                record.get('lambda', 1.0),
                record.get('R', 0.0),
                record.get('C', 0.0),
                record.get('rho_estimated', 0.0),
                record.get('cycle', 1)
            ])
            y_test.append(record['residual'])
        
        # 训练模型
        corrector = DensityCorrector()
        if corrector.train([{'residual': y_train[i], **{k: v for k, v in zip(['S', 'lambda', 'R', 'C', 'rho_estimated', 'cycle'], X_train[i])}} 
                          for i in range(len(y_train))]):
            # 在测试集上评估
            predictions = []
            for i, features in enumerate(X_test):
                correction = corrector.predict_correction(*features)
                predictions.append(correction)
            
            # 计算RMSE
            mse = sum((predictions[i] - y_test[i])**2 for i in range(len(y_test))) / len(y_test)
            rmse = math.sqrt(mse)
            cv_scores.append(rmse)
    
    if cv_scores:
        return {'rmse': statistics.mean(cv_scores), 'r_squared': 0.0}  # R²在CV中难以计算
    else:
        return {'rmse': float('inf'), 'r_squared': 0.0}

def main():
    """主函数：训练和评估密度校正模型"""
    # 加载数据
    data_file = 'E:\\workspace\\density-experiment\\residual-series.jsonl'
    data = load_residual_data(data_file)
    
    if not data:
        print("没有找到残差数据")
        return
    
    print(f"加载了 {len(data)} 条残差数据")
    validated_count = len([d for d in data if d.get('validation_status') == 'validated'])
    print(f"已验证: {validated_count} 条")
    
    if validated_count < 100:
        print(f"需要至少100条已验证样本才能训练模型，当前只有{validated_count}条")
        return
    
    # 训练模型
    corrector = DensityCorrector()
    success = corrector.train(data, sample_size=200)  # 最多使用200条样本
    
    if not success:
        print("模型训练失败")
        return
    
    print(f"\n模型训练完成:")
    print(f"样本数: {corrector.sample_count}")
    print(f"RMSE: {corrector.rmse:.4f}")
    print(f"R²: {corrector.r_squared:.4f}")
    
    # 时间序列交叉验证
    cv_results = time_series_cv(data)
    print(f"CV RMSE: {cv_results['rmse']:.4f}")
    
    # 计算基线误差（直接使用原始rho估计）
    baseline_errors = []
    for record in data:
        if record.get('validation_status') == 'validated':
            baseline_errors.append(abs(record['residual']))
    
    baseline_rmse = math.sqrt(sum(e**2 for e in baseline_errors) / len(baseline_errors)) if baseline_errors else float('inf')
    
    print(f"\n基线RMSE (原始ρ估计): {baseline_rmse:.4f}")
    print(f"改进比例: {(baseline_rmse - corrector.rmse) / baseline_rmse * 100:.1f}%")
    
    # 保存模型
    if (corrector.r_squared > 0.1 and 
        corrector.rmse < baseline_rmse and 
        (baseline_rmse - corrector.rmse) / baseline_rmse * 100 > 5):
        
        model_path = 'E:\\workspace\\density-experiment\\model\\density_corrector_current.json'
        import os
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        
        corrector.save_model(model_path)
        print(f"\n✅ 模型已保存: {model_path}")
        print("模型满足部署条件，将在下次裁决中使用")
    else:
        print(f"\n❌ 模型不满足部署条件")
        print("要求: R² > 0.1 且 RMSE改进 > 5%")

if __name__ == "__main__":
    main()