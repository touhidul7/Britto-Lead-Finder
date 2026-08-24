import unittest
from unittest.mock import Mock, patch

from listingsfinder.dedupe import dedupe_leads
from listingsfinder.lead_scraper import enrich_no_website_lead, lead_from_apify_place, lead_from_result
from listingsfinder.models import Lead
from listingsfinder.parser import parse_mandate
from listingsfinder.pipeline import _qualifies
from listingsfinder.queries import generate_queries
from listingsfinder import tmcp


class LeadFinderTests(unittest.TestCase):
    def test_parses_agency_lead_search(self):
        criteria = parse_mandate(
            "Find restaurants in Dhaka that need a better website and SEO exclude franchises"
        )
        self.assertEqual(criteria.industry, "Restaurants")
        self.assertEqual(criteria.location, "Dhaka")
        self.assertEqual(criteria.services, "Website Design, SEO")
        self.assertEqual(criteria.exclude, "franchises")

    def test_parses_strict_no_website_requirement(self):
        criteria = parse_mandate(
            "Find independent gyms in Ontario without a website and a publicly listed email. "
            "Exclude businesses with a website"
        )
        self.assertEqual(criteria.industry, "Gyms")
        self.assertEqual(criteria.location, "Ontario")
        self.assertEqual(criteria.website_requirement, "No Website")

    def test_no_website_filter_rejects_any_populated_website(self):
        no_site = Lead(source="Apify / Google Maps", company_name="Gym One", contact_email="gym@gmail.com")
        has_site = Lead(source="Apify / Google Maps", company_name="Gym Two", website="https://gym.ca", contact_email="hi@gym.ca")
        directory = Lead(source="Yelp", company_name="Gym Three", contact_email="gym3@gmail.com")
        self.assertTrue(_qualifies(no_site, True, "No Website"))
        self.assertFalse(_qualifies(has_site, True, "No Website"))
        self.assertFalse(_qualifies(directory, True, "No Website"))

    def test_enriches_no_website_lead_from_exact_name_social_result(self):
        lead = Lead(source="Apify / Google Maps", company_name="North Star Training", location="Ontario")
        enriched = enrich_no_website_lead(
            lead,
            [{
                "title": "North Star Training | Instagram",
                "url": "https://instagram.com/northstartraining",
                "snippet": "North Star Training Ontario. Email northstartraining@gmail.com",
            }],
            scrape_profiles=False,
        )
        self.assertEqual(enriched.contact_email, "northstartraining@gmail.com")
        self.assertEqual(enriched.instagram_url, "https://instagram.com/northstartraining")
        self.assertFalse(enriched.website)

    def test_queries_target_companies_not_business_sales(self):
        criteria = parse_mandate("Find dental clinics in Toronto that need SEO")
        queries = generate_queries(criteria, [])
        self.assertTrue(any("contact" in query for query in queries))
        self.assertFalse(any("business for sale" in query.lower() for query in queries))

    def test_accepts_singular_industry_page_for_plural_search(self):
        criteria = parse_mandate("Find dentists in Toronto that need SEO")
        lead = lead_from_result(
            {
                "url": "https://example-dental.com",
                "title": "Example Dental | Toronto Dentist",
                "snippet": "Toronto dental clinic. Call 416-555-1234",
                "source": "test",
                "query": "dentist Toronto",
            },
            criteria,
            scrape_pages=False,
        )
        self.assertIsNotNone(lead)
        self.assertEqual(lead.industry, "Dentists")
        self.assertEqual(lead.location, "Toronto")

    def test_deduplicates_same_company_domain(self):
        first = Lead(lead_id="1", company_name="Acme", website="https://acme.com")
        second = Lead(lead_id="2", company_name="Acme Ltd", website="https://www.acme.com/about")
        masters, duplicates = dedupe_leads([first, second])
        self.assertEqual(len(masters), 1)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["Reason"], "Same website domain")

    def test_maps_apify_place_to_lead(self):
        criteria = parse_mandate("Find restaurants in Dhaka that need web design")
        lead = lead_from_apify_place(
            {
                "title": "Britto Cafe", "website": "https://cafe.example",
                "url": "https://maps.google.com/example", "phone": "+880 1700 000000",
                "categoryName": "Restaurant", "city": "Dhaka", "placeId": "place-1",
            },
            criteria,
            scrape_pages=False,
        )
        self.assertEqual(lead.source, "Apify / Google Maps")
        self.assertEqual(lead.company_name, "Britto Cafe")
        self.assertEqual(lead.location, "Dhaka")

    def test_reads_apify_enriched_email_and_social_profiles(self):
        criteria = parse_mandate("Find dentists in Toronto that need SEO")
        lead = lead_from_apify_place(
            {
                "title": "Toronto Dental", "website": "https://dental.example.org",
                "city": "Toronto", "placeId": "place-2",
                "contacts": {"emails": ["hello@dental.example.org"]},
                "socials": {
                    "facebook": "https://facebook.com/torontodental",
                    "instagram": "https://instagram.com/torontodental",
                    "linkedin": "https://linkedin.com/company/toronto-dental",
                },
            },
            criteria,
            scrape_pages=False,
        )
        self.assertEqual(lead.contact_email, "hello@dental.example.org")
        self.assertEqual(lead.email_source, "Apify contact enrichment")
        self.assertIn("facebook.com", lead.facebook_url)
        self.assertIn("instagram.com", lead.instagram_url)
        self.assertIn("linkedin.com", lead.linkedin_url)

    @patch("listingsfinder.lead_scraper.fetch_url")
    def test_crawls_contact_page_for_email_and_social_links(self, fetch_url):
        fetch_url.side_effect = [
            (
                '<html><head><title>Toronto Dentist</title></head><body>'
                '<p>Dental clinic in Toronto</p><a href="/contact">Contact us</a>'
                '<a href="https://instagram.com/torontodentist">Instagram</a></body></html>',
                "direct",
            ),
            ('<html><body><a href="mailto:hello@torontodentist.ca">Email us</a></body></html>', "direct"),
        ]
        criteria = parse_mandate("Find dentists in Toronto that need SEO")
        lead = lead_from_result(
            {
                "url": "https://torontodentist.ca", "title": "Toronto Dentist",
                "snippet": "Dental clinic in Toronto", "source": "test", "query": "dentist Toronto",
            },
            criteria,
            scrape_pages=True,
        )
        self.assertIsNotNone(lead)
        self.assertEqual(lead.contact_email, "hello@torontodentist.ca")
        self.assertEqual(lead.email_source, "https://torontodentist.ca/contact")
        self.assertEqual(lead.instagram_url, "https://instagram.com/torontodentist")

    @patch("listingsfinder.tmcp.requests.post")
    def test_apify_uses_tmcp_rotate_proxy(self, post):
        response = Mock()
        response.json.return_value = [{"title": "Example"}]
        response.raise_for_status.return_value = None
        post.return_value = response
        with patch.object(tmcp, "TMCP_API_KEY", "test-key"):
            rows = tmcp.apify_google_maps_search("restaurant", "Dhaka", 5)
        self.assertEqual(rows[0]["title"], "Example")
        args, kwargs = post.call_args
        self.assertIn("/api/apify/v2/acts/", args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        actor_input = kwargs["json"]
        self.assertTrue(actor_input["scrapeContacts"])
        self.assertTrue(actor_input["scrapeSocialMediaProfiles"]["facebooks"])
        self.assertGreaterEqual(actor_input["maximumLeadsEnrichmentRecords"], 1)

    @patch("listingsfinder.tmcp.requests.post")
    def test_openrouter_uses_tmcp_rotate_proxy(self, post):
        response = Mock()
        response.json.return_value = {"choices": []}
        response.raise_for_status.return_value = None
        post.return_value = response
        with patch.object(tmcp, "TMCP_API_KEY", "test-key"):
            tmcp.openrouter_chat({"model": "test", "messages": []})
        args, kwargs = post.call_args
        self.assertTrue(args[0].endswith("/api/openrouter/v1/chat/completions"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")


if __name__ == "__main__":
    unittest.main()
