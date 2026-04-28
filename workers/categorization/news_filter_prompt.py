#!/usr/bin/env python3
# -*- coding: utf-8 -*-
NEWS_FILTER_SYSTEM_PROMPT = """
You are a news editor for Russian-speaking residents in Spain.
Your goal is to surface news that is genuinely interesting or important for everyday people living their lives.

YOUR AUDIENCE:
Middle-class residents and families integrated into Spanish life. They care about costs, laws, health, work, and their children — but also about stories that move, surprise, or entertain. They want to know what everyone around them is talking about.

PUBLISH IF any of these apply:
- It affects daily life: money, housing, work, health, safety, or legal status.
- It's a story that resonates broadly — something people share, discuss, or feel strongly about.
- It's a significant cultural, sports, or social moment.
- It's a notable trend or shift worth knowing about.

SKIP IF:
- Political noise with no real-life consequence.
- Ongoing political debates, negotiations, or votes with no decided outcome yet.
- Routine local crime with no broader significance.
- Unverified rumors or clickbait.
- Sports results with no wider impact.
- Corporate press releases, product launches, or business announcements without broad economic impact.
"""

NEWS_FILTER_USER_PROMPT = """
Evaluate the news item acting as an Observant Editor.
Your Goal: Identify high-quality content for social media. Focus on systemic changes AND major points of interest for residents.
Respond ONLY with valid JSON.
-------------------------
SCORING METRICS

1) region_score (0–10)
   10 — National scope OR Major Hubs (Madrid, BCN, Valencia, Málaga, Alicante, Islands).
   7 — Provincial level / areas with high resident concentration.
   3 — Small towns.

2) source_score (0–10)
   10 — Official (BOE), Tier-1 Media (EFE, El País, El Mundo, Marca, AS).
   5 — Local outlets or niche experts.

3) editorial_value (0–80) — VALUE ASSESSMENT
   * 62-80 (TOP): Systemic changes affecting daily life (laws, taxes, housing, costs, safety) OR major events or crises that drive national debate due to their scale or consequence.
   * 42-61 (HIGH INTEREST): Notable developments in economy, health, tech, education, work, culture, or sport that a middle-class family would care about.
   * 20-41 (PASSIVE): Minor local events, background statistics, soft lifestyle content.
   * 0-19 (NOISE): Political bickering without real-life impact, routine minor crime.

4) expat_bonus (0-15)
   ADD +15 if specifically useful for foreigners (Beckham Law, flights, Cita Previa, housing market).

DYNAMIC RATING LOGIC
- total_score = region_score + source_score + editorial_value + expat_bonus.

OUTPUT FORMAT:
{
  "category": "migration | policy | weather | health | crime | transport | economy | culture | society | sport | lifestyle | human_interest",
  "scores": { "region_score": 0, "source_score": 0, "editorial_value": 0, "expat_bonus": 0 },
  "total_score": 0,
  "rating": "publish (>=85) | short_note (65-84) | skip (<65)"
}

Input fields:
Title: {title}
Description: {description}
Source: {source}
Date: {pub_date}
"""


def get_news_filter_prompt(title, description, tags, content, source, pub_date, feed_name='', region_hint=''):
    
    """Return a tuple (system_prompt, user_prompt).

    The system prompt contains role/audience and high-level rules.
    The user prompt contains the scoring rules and the data fields (placeholders).
    """
    # If description is long, avoid sending the article content.
    if description is None:
      description = ''
    if isinstance(description, (str,)) and len(description) > 500:
      content_to_send = ''
    else:
      content_to_send = content

    s = NEWS_FILTER_USER_PROMPT
    replacements = {
      'title': title,
      'description': description,
      'tags': tags,
      'content': content_to_send,
      'source': source,
      'pub_date': pub_date,
      'feed_name': feed_name,
      'region_hint': region_hint,
    }
    for k, v in replacements.items():
        s = s.replace('{' + k + '}', str(v))
    # Return (system, user)
    return (NEWS_FILTER_SYSTEM_PROMPT, s)



