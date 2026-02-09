# Daily Health Summary Template

## Daily Health Summary - YYYY-MM-DD

### Diet Overview
- **Calories consumed**: X,XXX kcal
- **Protein**: XXXg ([XX%] of target — from config: weight_kg * protein_per_kg)
- **Carbs**: XXXg
- **Fat**: XXg
- **Fiber**: XXg (target: from config fiber_target_g, default 38g)
- **Sodium**: X,XXXmg (warning: > config sodium_limit_mg, default 2,300mg)

### Fitness Overview
- **Steps**: X,XXX steps
- **Calories burned**: X,XXX kcal
- **Resting heart rate**: XX bpm
- **Sleep**: Xh Xm (quality: good/fair/poor)
- **Weight**: XX.X kg
- **Distance**: X.XX km

### Net Balance
- **Calorie balance**: +/-XXX kcal (consumed - burned)
- **Protein status**: [Excellent/Good/Fair/Needs improvement]
- **Movement**: [Sedentary/Light/Moderate/Active/Very active]

### Meal Breakdown
- **Breakfast**: XXX kcal (X meals)
- **Lunch**: XXX kcal (X meals)
- **Dinner**: XXX kcal (X meals)
- **Snacks**: XXX kcal (X snacks)

### Coach's Notes

**Strengths:**
- [Highlight positive choices]
- [Note good protein intake]
- [Praise healthy options]

**Areas for improvement:**
- [Identify weaknesses]
- [Suggest improvements]
- [Note missed targets]

**Tomorrow's focus:**
- [1-2 specific goals]
- [Meal suggestions]
- [Activity recommendations]

---

## Summary Analysis Logic

### Protein Assessment (relative to weight_kg * protein_per_kg from config)
- **Excellent**: >125% of target
- **Good**: 100-125% of target
- **Fair**: 75-100% of target
- **Needs improvement**: <75% of target

### Movement Assessment
- **Sedentary**: <5,000 steps
- **Light**: 5,000-7,999 steps
- **Moderate**: 8,000-11,999 steps
- **Active**: 12,000-15,999 steps
- **Very active**: >16,000 steps

### Calorie Balance
- **Deficit** (< -300 kcal): Weight loss potential
- **Maintenance** (-300 to +300 kcal): Maintaining weight
- **Surplus** (> +300 kcal): Potential weight gain

### Sleep Quality (relative to sleep_target_h from config, default 7h)
- **Good**: >= target
- **Fair**: target-2 to target
- **Poor**: < target-2
