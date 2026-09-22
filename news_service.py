import re
import html
import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
import httpx

logger = logging.getLogger("NewsService")

# 100% Verified Bangladesh Focused Real-time RSS Feeds
RSS_FEEDS = {
    "national": "https://news.google.com/rss/search?q=বাংলাদেশ+জাতীয়+সংবাদ&hl=bn&gl=BD&ceid=BD:bn",
    "international": "https://news.google.com/rss/search?q=বিশ্ব+আন্তর্জাতিক+সংবাদ&hl=bn&gl=BD&ceid=BD:bn",
    "sports": "https://news.google.com/rss/search?q=বাংলাদেশ+খেলাধুলা+ক্রিকেট&hl=bn&gl=BD&ceid=BD:bn",
    "tech": "https://news.google.com/rss/search?q=প্রযুক্তি+সংবাদ&hl=bn&gl=BD&ceid=BD:bn"
}

BN_NUMERALS = {1: "১", 2: "২", 3: "৩", 4: "৪", 5: "৫"}

class NewsService:
    def __init__(self):
        self.seen_news_ids = set()
        self.last_breaking_headline = ""

    def _clean_text(self, raw_html: str) -> str:
        if not raw_html:
            return ""
        clean = re.sub(r'<[^>]+>', ' ', raw_html)
        clean = html.unescape(clean)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()

    async def fetch_feed(self, url: str, limit: int = 4) -> List[Dict[str, str]]:
        """Fetches and parses Bangladesh RSS news feed asynchronously."""
        items = []
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"News fetch HTTP {resp.status_code} for {url}")
                    return items

                root = ET.fromstring(resp.content)
                for item in root.findall(".//item"):
                    if len(items) >= limit:
                        break
                    title_elem = item.find("title")
                    link_elem = item.find("link")
                    pub_date_elem = item.find("pubDate")
                    source_elem = item.find("source")

                    title = self._clean_text(title_elem.text if title_elem is not None else "")
                    link = link_elem.text if link_elem is not None else ""
                    pub_date = pub_date_elem.text if pub_date_elem is not None else ""
                    source = source_elem.text if source_elem is not None else "জাতীয় সংবাদ"

                    # Clean redundant source names from the end of title
                    if " - " in title:
                        parts = title.rsplit(" - ", 1)
                        title = parts[0].strip()
                        if source in ["জাতীয় সংবাদ", "Google News"]:
                            source = parts[1].strip()

                    # Clean pipe suffixes (e.g. " | জাতীয় | প্রথম আলো")
                    if " | " in title:
                        parts = title.split(" | ")
                        title = parts[0].strip()

                    # Filter out Indian West Bengal news if any leaks through
                    if any(w in title for w in ["মমতা", "তৃণমূল", "নবান্ন", "কালীঘাট", "কলকাতা", "নন্দীগ্রাম", "পশ্চিমবঙ্গ"]):
                        continue

                    if title:
                        items.append({
                            "title": title,
                            "link": link,
                            "source": source,
                            "pub_date": pub_date
                        })
        except Exception as e:
            logger.error(f"Error fetching news feed {url}: {e}")
        return items

    async def get_live_news_bulletin(self, category: str = "all") -> Dict[str, Any]:
        """Returns structured news bulletin (markdown for chat + sweet natural speech for female voice)."""
        category = category.lower().strip()
        feed_url = RSS_FEEDS.get("national")
        cat_title = "বাংলাদেশের জাতীয় ও প্রধান সংবাদ"

        if any(k in category for k in ["inter", "bidesh", "বিদেশের", "বিশ্ব", "world", "আন্তর্জাতিক"]):
            feed_url = RSS_FEEDS.get("international")
            cat_title = "বিশ্ব ও আন্তর্জাতিক সংবাদ"
        elif any(k in category for k in ["tech", "প্রযুক্তি", "science", "বিজ্ঞান", "technology"]):
            feed_url = RSS_FEEDS.get("tech")
            cat_title = "বিজ্ঞান ও প্রযুক্তি সংবাদ"
        elif any(k in category for k in ["sport", "খেলা", "cricket", "football", "ফুটবল", "ক্রিকেট", "sports"]):
            feed_url = RSS_FEEDS.get("sports")
            cat_title = "খেলাধুলার তাজা খবর"
        else:
            feed_url = RSS_FEEDS.get("national")
            cat_title = "বাংলাদেশের জাতীয় সংবাদ"

        articles = await self.fetch_feed(feed_url, limit=3)

        if not articles:
            return {
                "category": cat_title,
                "articles": [],
                "formatted_markdown": "দুঃখিত বাবু, এই মুহূর্তে লাইভ সংবাদ সার্ভারের সাথে সংযোগ করা যাচ্ছে না। একটু পর আবার চেষ্টা করো!",
                "spoken_summary": "দুঃখিত প্রিয়, এই মুহূর্তে লাইভ খবরের সার্ভারে একটু সমস্যা হচ্ছে।"
            }

        # Clean Markdown for visual chat box
        md_lines = [f"### 📰 {cat_title}\n"]
        spoken_points = []

        for idx, art in enumerate(articles, 1):
            bn_num = BN_NUMERALS.get(idx, str(idx))
            md_lines.append(f"**{bn_num}. {art['title']}**")
            md_lines.append(f"   *সূত্র: {art['source']}* [বিস্তারিত পড়ুন ↗]({art['link']})\n")
            spoken_points.append(f"{bn_num} নম্বর, {art['title']}")

        formatted_markdown = "\n".join(md_lines)

        # Pure, natural sweet Bengali text crafted exclusively for Cartesia & Female Voice
        spoken_summary = (
            f"বাবু! {cat_title} এর শীর্ষ খবরগুলো হলো: "
            + "। এরপরে, ".join(spoken_points)
            + "। বিস্তারিত পড়তে চ্যাট বক্সে লিংক দিয়েছি প্রিয়!"
        )

        return {
            "category": cat_title,
            "articles": articles,
            "formatted_markdown": formatted_markdown,
            "spoken_summary": spoken_summary
        }

    async def check_breaking_news(self) -> Optional[Dict[str, Any]]:
        """Checks for new high-priority Bangladesh breaking news stories."""
        try:
            articles = await self.fetch_feed(RSS_FEEDS["national"], limit=2)
            if not articles:
                return None

            top_article = articles[0]
            headline = top_article["title"]

            if headline and headline != self.last_breaking_headline and headline not in self.seen_news_ids:
                self.seen_news_ids.add(headline)
                if len(self.seen_news_ids) > 100:
                    self.seen_news_ids.pop()

                is_first_run = (self.last_breaking_headline == "")
                self.last_breaking_headline = headline

                if not is_first_run:
                    return {
                        "title": headline,
                        "source": top_article.get("source", "বাংলাদেশের সংবাদ"),
                        "link": top_article.get("link", "#"),
                        "spoken_alert": f"বাবু! একটি জরুরি ব্রেকিং নিউজ এসেছে: {headline}"
                    }
        except Exception as e:
            logger.debug(f"Error checking breaking news: {e}")
        return None

news_service = NewsService()
