"""
AI Governor Bot - Risk Scoring Engine
Mathematically optimized multi-factor risk calculation system
"""

import math
import hashlib
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio

from config.settings import get_settings, RISK_WEIGHTS


@dataclass
class RiskFactors:
    """Container for all risk factor scores."""
    spam: float = 0.0
    toxic: float = 0.0
    scam: float = 0.0
    illegal: float = 0.0
    phishing: float = 0.0
    nsfw: float = 0.0
    flood: float = 0.0
    user_history: float = 0.0
    similarity: float = 0.0
    link_suspicious: float = 0.0
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "spam": self.spam,
            "toxic": self.toxic,
            "scam": self.scam,
            "illegal": self.illegal,
            "phishing": self.phishing,
            "nsfw": self.nsfw,
            "flood": self.flood,
            "user_history": self.user_history,
            "similarity": self.similarity,
            "link_suspicious": self.link_suspicious,
        }


@dataclass
class RiskAssessment:
    """Complete risk assessment result."""
    final_score: float
    normalized_score: float
    risk_level: str
    factors: RiskFactors
    decision: str
    action: str
    confidence: float
    processing_time_ms: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_score": self.final_score,
            "normalized_score": self.normalized_score,
            "risk_level": self.risk_level,
            "factors": self.factors.to_dict(),
            "decision": self.decision,
            "action": self.action,
            "confidence": self.confidence,
            "processing_time_ms": self.processing_time_ms,
        }


class RiskScoringEngine:
    """
    Mathematically optimized risk scoring engine.
    Implements the weighted multi-factor risk formula with dynamic escalation.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.weights = RISK_WEIGHTS
        self._cache = {}
        
    async def calculate_risk(
        self,
        message_text: str,
        user_id: int,
        group_id: int,
        ai_analysis: Dict[str, Any],
        user_history: Dict[str, Any],
        context: Dict[str, Any],
    ) -> RiskAssessment:
        """
        Calculate comprehensive risk score using the mathematical formula.
        
        Formula: R = 1 - Π(1 - Wi * Si)
        Where Wi = weight, Si = normalized score
        """
        start_time = datetime.utcnow()
        
        # Extract base scores from AI analysis
        factors = RiskFactors(
            spam=ai_analysis.get("spam", 0.0),
            toxic=ai_analysis.get("toxicity", 0.0),
            scam=ai_analysis.get("scam", 0.0),
            illegal=ai_analysis.get("illegal", 0.0),
            phishing=ai_analysis.get("phishing", 0.0),
            nsfw=ai_analysis.get("nsfw", 0.0),
        )
        
        # Calculate flood factor
        factors.flood = await self._calculate_flood_factor(user_id, group_id, context)
        
        # Calculate user history factor
        factors.user_history = self._calculate_user_history_factor(user_history)
        
        # Calculate similarity factor (duplicate detection)
        factors.similarity = await self._calculate_similarity_factor(message_text, group_id)
        
        # Calculate link suspiciousness
        factors.link_suspicious = self._calculate_link_factor(message_text, ai_analysis)
        
        # Apply weighted multi-factor formula
        raw_score = self._apply_risk_formula(factors)
        
        # Apply dynamic escalation
        escalated_score = self._apply_dynamic_escalation(
            raw_score, user_history, factors
        )
        
        # Apply sigmoid smoothing
        normalized_score = self._sigmoid_smooth(escalated_score)
        
        # Scale to 0-100
        final_score = normalized_score * 100
        
        # Determine risk level and action
        risk_level, decision, action = self._determine_action(final_score, factors)
        
        processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        return RiskAssessment(
            final_score=final_score,
            normalized_score=normalized_score,
            risk_level=risk_level,
            factors=factors,
            decision=decision,
            action=action,
            confidence=self._calculate_confidence(factors, ai_analysis),
            processing_time_ms=processing_time,
        )
    
    async def _calculate_flood_factor(
        self, user_id: int, group_id: int, context: Dict
    ) -> float:
        """Calculate flood/spam velocity factor."""
        recent_messages = context.get("recent_user_messages", 0)
        time_window = context.get("time_window_seconds", 60)
        
        if recent_messages == 0 or time_window == 0:
            return 0.0
        
        # Messages per minute
        rate = (recent_messages / time_window) * 60
        
        # Normalize: 0-5 messages/min = 0, 5-20 = linear, >20 = 1.0
        if rate <= 5:
            return 0.0
        elif rate >= 20:
            return 1.0
        else:
            return (rate - 5) / 15
    
    def _calculate_user_history_factor(self, user_history: Dict) -> float:
        """Calculate risk based on user's violation history."""
        violations_24h = user_history.get("violations_24h", 0)
        violations_7d = user_history.get("violations_7d", 0)
        total_violations = user_history.get("total_violations", 0)
        trust_score = user_history.get("trust_score", 50)
        
        # Recent violations are weighted more heavily
        recent_factor = min(violations_24h * 0.3 + violations_7d * 0.1, 1.0)
        
        # Trust score inverse (lower trust = higher risk)
        trust_factor = max(0, (50 - trust_score) / 50)
        
        # Combine factors
        return min((recent_factor * 0.6 + trust_factor * 0.4), 1.0)
    
    async def _calculate_similarity_factor(self, message_text: str, group_id: int) -> float:
        """Calculate similarity to recent messages (duplicate detection)."""
        if not message_text or len(message_text) < 10:
            return 0.0
        
        # This would typically query recent messages from cache/DB
        # For now, return placeholder - actual implementation uses Redis cache
        return 0.0
    
    def _calculate_link_factor(self, message_text: str, ai_analysis: Dict) -> float:
        """Calculate suspicious link factor."""
        if not message_text:
            return 0.0
        
        # Use AI analysis for links
        link_score = ai_analysis.get("suspicious_links", 0.0)
        phishing_score = ai_analysis.get("phishing", 0.0)
        
        return max(link_score, phishing_score * 0.8)
    
    def _apply_risk_formula(self, factors: RiskFactors) -> float:
        """
        Apply the weighted multi-factor risk formula.
        R = 1 - Π(1 - Wi * Si)
        """
        factor_values = [
            (self.weights["spam"], factors.spam),
            (self.weights["toxic"], factors.toxic),
            (self.weights["scam"], factors.scam),
            (self.weights["illegal"], factors.illegal),
            (self.weights["phishing"], factors.phishing),
            (self.weights["nsfw"], factors.nsfw),
            (self.weights["flood"], factors.flood),
            (self.weights["user_history"], factors.user_history),
            (self.weights["similarity"], factors.similarity),
            (self.weights["link_suspicious"], factors.link_suspicious),
        ]
        
        # Calculate product of (1 - Wi * Si)
        product = 1.0
        for weight, score in factor_values:
            product *= (1 - weight * score)
        
        # Final risk score
        risk = 1 - product
        return min(max(risk, 0.0), 1.0)
    
    def _apply_dynamic_escalation(
        self, 
        raw_score: float, 
        user_history: Dict,
        factors: RiskFactors
    ) -> float:
        """Apply dynamic escalation based on user history and patterns."""
        escalation_multiplier = 1.0
        
        # Violation count escalation
        violations_24h = user_history.get("violations_24h", 0)
        if violations_24h > 3:
            escalation_multiplier *= 1.15
        
        # Trust score escalation
        trust_score = user_history.get("trust_score", 50)
        if trust_score < 20:
            escalation_multiplier *= 1.25
        
        # Apply escalation
        escalated = raw_score * escalation_multiplier
        return min(escalated, 1.0)
    
    def _sigmoid_smooth(self, score: float, k: float = 10.0) -> float:
        """Apply sigmoid smoothing for fairer scoring."""
        return 1 / (1 + math.exp(-k * (score - 0.5)))
    
    def _determine_action(
        self, 
        final_score: float, 
        factors: RiskFactors
    ) -> Tuple[str, str, str]:
        """Determine risk level, decision, and action based on final score."""
        settings = get_settings()
        
        # Determine risk level
        if final_score >= settings.RISK_THRESHOLD_CRITICAL:
            risk_level = "critical"
            decision = "block"
            action = "delete_mute_notify"
        elif final_score >= settings.RISK_THRESHOLD_HIGH:
            risk_level = "high"
            decision = "block"
            action = "delete_warn"
        elif final_score >= settings.RISK_THRESHOLD_MEDIUM:
            risk_level = "medium"
            decision = "warn"
            action = "soft_warn_monitor"
        else:
            risk_level = "low"
            decision = "allow"
            action = "allow"
        
        return risk_level, decision, action
    
    def _calculate_confidence(
        self, 
        factors: RiskFactors, 
        ai_analysis: Dict
    ) -> float:
        """Calculate confidence level in the risk assessment."""
        # Base confidence from AI
        ai_confidence = ai_analysis.get("confidence", 0.8)
        
        # Factor variance (higher variance = lower confidence)
        factor_values = [
            factors.spam, factors.toxic, factors.scam,
            factors.illegal, factors.phishing, factors.nsfw
        ]
        variance = sum((x - sum(factor_values)/len(factor_values))**2 for x in factor_values) / len(factor_values)
        variance_penalty = min(variance * 2, 0.2)
        
        # Final confidence
        confidence = max(0.5, ai_confidence - variance_penalty)
        return round(confidence, 2)


# Global risk engine instance
risk_engine = RiskScoringEngine()
