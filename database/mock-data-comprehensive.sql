-- =====================================================
-- CRM Application - Comprehensive Mock Data for UI/UX Design & Testing
-- Contains 20+ records in all primary sections covering every status, stage, and edge-case
-- =====================================================

-- 1. USERS (Password for all users: Password@123)
-- Password hash: $2b$10$XwsKGSpPqvM.mcb4Dmtaeei7PvZ57qM/rBPnE2BRilQRDaTfxZJdW
INSERT INTO users (id, full_name, email, password_hash, role, is_active, team_access, reports_to_id) VALUES
(2, 'Priya Sharma',    'priya@crm.test',   '$2b$10$XwsKGSpPqvM.mcb4Dmtaeei7PvZ57qM/rBPnE2BRilQRDaTfxZJdW', 'Manager',     TRUE, TRUE,  NULL),
(3, 'Marcus Vance',    'marcus@crm.test',  '$2b$10$XwsKGSpPqvM.mcb4Dmtaeei7PvZ57qM/rBPnE2BRilQRDaTfxZJdW', 'Manager',     TRUE, TRUE,  NULL),
(4, 'Ravi Kumar',      'ravi@crm.test',    '$2b$10$XwsKGSpPqvM.mcb4Dmtaeei7PvZ57qM/rBPnE2BRilQRDaTfxZJdW', 'Salesperson', TRUE, FALSE, 2),
(5, 'Anita Desai',     'anita@crm.test',   '$2b$10$XwsKGSpPqvM.mcb4Dmtaeei7PvZ57qM/rBPnE2BRilQRDaTfxZJdW', 'Salesperson', TRUE, FALSE, 2),
(6, 'Alex Chen',       'alex@crm.test',    '$2b$10$XwsKGSpPqvM.mcb4Dmtaeei7PvZ57qM/rBPnE2BRilQRDaTfxZJdW', 'Salesperson', TRUE, TRUE,  3),
(7, 'Sarah Jenkins',   'sarah@crm.test',   '$2b$10$XwsKGSpPqvM.mcb4Dmtaeei7PvZ57qM/rBPnE2BRilQRDaTfxZJdW', 'Salesperson', TRUE, FALSE, 3)
ON CONFLICT (id) DO UPDATE SET 
  full_name = EXCLUDED.full_name,
  email = EXCLUDED.email,
  role = EXCLUDED.role;

-- 2. ACCOUNTS (22 Companies across industries)
INSERT INTO accounts (id, name, industry, phone, website, address, linkedin_url, annual_revenue, employees, owner_id) VALUES
(1,  'Sunrise Health Systems', 'Healthcare',     '+1 415-555-0101', 'sunrisehealth.org',   '100 Medical Center Way, San Francisco, CA', 'https://linkedin.com/company/sunrise-health', 15000000.00, 450, 1),
(2,  'GreenLeaf Organics',     'FMCG',           '+1 212-555-0102', 'greenleaforganics.com', '45 Hudson St, New York, NY',                 'https://linkedin.com/company/greenleaf-organics', 8500000.00,  180, 4),
(3,  'Apex Freight Logistics', 'Logistics',      '+1 312-555-0103', 'apexlogistics.io',     '780 W Randolph St, Chicago, IL',            'https://linkedin.com/company/apex-logistics', 24000000.00, 620, 5),
(4,  'Nova Smart Textiles',    'Manufacturing',  '+1 617-555-0104', 'novatextiles.com',     '12 Innovation Way, Boston, MA',             'https://linkedin.com/company/nova-textiles', 12000000.00, 310, 6),
(5,  'CloudPulse Networks',    'Technology',     '+1 408-555-0105', 'cloudpulse.net',       '300 Tech Parkway, San Jose, CA',            'https://linkedin.com/company/cloudpulse', 35000000.00, 850, 4),
(6,  'Vanguard FinTech',       'Finance',        '+1 212-555-0106', 'vanguardfin.io',       '200 Wall Street, New York, NY',             'https://linkedin.com/company/vanguard-fintech', 45000000.00, 1100, 1),
(7,  'Beacon Media Labs',      'Media',          '+1 310-555-0107', 'beaconmedia.co',       '1450 Ocean Ave, Santa Monica, CA',          'https://linkedin.com/company/beacon-media', 6500000.00,  95,  5),
(8,  'Zenith Solar Energy',    'Energy',         '+1 512-555-0108', 'zenithsolar.com',      '800 Congress Ave, Austin, TX',              'https://linkedin.com/company/zenith-solar', 18000000.00, 290, 7),
(9,  'Aegis Cybersecurity',    'Security',       '+1 703-555-0109', 'aegissecurity.io',     '1750 Tysons Blvd, McLean, VA',              'https://linkedin.com/company/aegis-security', 22000000.00, 400, 6),
(10, 'BlueRidge Heavy Gear',   'Construction',   '+1 704-555-0110', 'blueridgegear.com',    '550 South Tryon St, Charlotte, NC',         'https://linkedin.com/company/blueridge-gear', 31000000.00, 720, 4),
(11, 'OmniRetail Solutions',   'Retail',         '+1 206-555-0111', 'omniretail.com',       '1201 3rd Ave, Seattle, WA',                 'https://linkedin.com/company/omni-retail', 19500000.00, 510, 5),
(12, 'Summit BioLabs',         'Biotechnology',  '+1 617-555-0112', 'summitbiolabs.com',    '400 Technology Square, Cambridge, MA',      'https://linkedin.com/company/summit-biolabs', 14000000.00, 230, 1),
(13, 'Titan Robotics',         'Robotics',       '+1 412-555-0113', 'titanrobotics.ai',     '2500 Smallman St, Pittsburgh, PA',          'https://linkedin.com/company/titan-robotics', 28000000.00, 380, 6),
(14, 'Pulse Hospitality Group','Hospitality',    '+1 305-555-0114', 'pulsehospitality.com', '1100 Biscayne Blvd, Miami, FL',            'https://linkedin.com/company/pulse-hospitality', 16500000.00, 600, 7),
(15, 'Quantum Data Systems',   'Data & AI',      '+1 415-555-0115', 'quantumdata.ai',       '500 Howard St, San Francisco, CA',          'https://linkedin.com/company/quantum-data', 50000000.00, 950, 4),
(16, 'Silverline Automotive',  'Automotive',     '+1 313-555-0116', 'silverlineauto.com',   '100 Renaissance Ctr, Detroit, MI',          'https://linkedin.com/company/silverline-auto', 42000000.00, 1300, 5),
(17, 'Astraea Aerospace',      'Aerospace',      '+1 303-555-0117', 'astraea-aero.com',     '1801 California St, Denver, CO',            'https://linkedin.com/company/astraea-aero', 65000000.00, 1600, 1),
(18, 'NorthStar Education',    'Education',      '+1 612-555-0118', 'northstaredu.org',     '80 S 8th St, Minneapolis, MN',              'https://linkedin.com/company/northstar-edu', 9000000.00,  210, 6),
(19, 'Crestview Capital',      'Banking',        '+1 212-555-0119', 'crestviewcap.com',     '375 Park Ave, New York, NY',                'https://linkedin.com/company/crestview-cap', 80000000.00, 1400, 7),
(20, 'Veritas Legal Tech',     'Legal',          '+1 202-555-0120', 'veritaslegal.io',      '1050 Connecticut Ave NW, Washington, DC',   'https://linkedin.com/company/veritas-legal', 7500000.00,  120, 4),
(21, 'Harbor Cold Storage',    'Warehousing',    '+1 912-555-0121', 'harborstorage.com',    '2 E Bryan St, Savannah, GA',                'https://linkedin.com/company/harbor-storage', 11000000.00, 260, 5),
(22, 'Elevate Insurance Co',   'Insurance',      '+1 860-555-0122', 'elevateinsurance.com', '1 State St, Hartford, CT',                 'https://linkedin.com/company/elevate-ins', 38000000.00, 890, 1)
ON CONFLICT (id) DO NOTHING;

-- 3. CONTACTS (25 Key Decision Makers linked to Accounts)
INSERT INTO contacts (id, salutation, first_name, last_name, job_title, email, phone, linkedin_url, account_id, owner_id) VALUES
(1,  'Dr.',  'Meera',   'Iyer',       'Director of Operations',  'meera@sunrisehealth.org',   '+1 415-555-1001', 'https://linkedin.com/in/meera-iyer',       1,  1),
(2,  'Mr.',  'Rahul',   'Nair',       'Chief Information Officer','rahul@sunrisehealth.org',  '+1 415-555-1002', 'https://linkedin.com/in/rahul-nair',       1,  1),
(3,  'Mr.',  'Arjun',   'Mehta',      'VP of Supply Chain',      'arjun@greenleaforganics.com','+1 212-555-1003', 'https://linkedin.com/in/arjun-mehta',      2,  4),
(4,  'Ms.',  'Kavya',   'Reddy',      'COO & Head of Logistics', 'kavya@apexlogistics.io',    '+1 312-555-1004', 'https://linkedin.com/in/kavya-reddy',      3,  5),
(5,  'Mr.',  'Sanjay',  'Patel',      'Director of Procurement', 'sanjay@novatextiles.com',   '+1 617-555-1005', 'https://linkedin.com/in/sanjay-patel',     4,  6),
(6,  'Ms.',  'Elena',   'Rostova',    'VP of Infrastructure',    'elena@cloudpulse.net',      '+1 408-555-1006', 'https://linkedin.com/in/elena-rostova',    5,  4),
(7,  'Mr.',  'Jonathan','Drake',      'Head of Risk Engineering','jdrake@vanguardfin.io',     '+1 212-555-1007', 'https://linkedin.com/in/jonathan-drake',   6,  1),
(8,  'Ms.',  'Chloe',   'Simmons',    'Creative Director',       'chloe@beaconmedia.co',      '+1 310-555-1008', 'https://linkedin.com/in/chloe-simmons',    7,  5),
(9,  'Mr.',  'David',   'Sterling',   'VP of Clean Grid Ops',    'dsterling@zenithsolar.com', '+1 512-555-1009', 'https://linkedin.com/in/david-sterling',   8,  7),
(10, 'Dr.',  'Amara',   'Okafor',     'Chief Security Officer',  'aokafor@aegissecurity.io',  '+1 703-555-1010', 'https://linkedin.com/in/amara-okafor',     9,  6),
(11, 'Mr.',  'Robert',  'MacKenzie',  'Fleet Maintenance Dir.',  'rmack@blueridgegear.com',   '+1 704-555-1011', 'https://linkedin.com/in/robert-mackenzie', 10, 4),
(12, 'Ms.',  'Sophia',  'Martinez',   'Head of Digital Commerce','smartinez@omniretail.com',  '+1 206-555-1012', 'https://linkedin.com/in/sophia-martinez',  11, 5),
(13, 'Dr.',  'Gregory', 'House',      'Head of Clinical Research','ghouse@summitbiolabs.com',  '+1 617-555-1013', 'https://linkedin.com/in/gregory-house',    12, 1),
(14, 'Mr.',  'Kenji',   'Takahashi',  'Automation Lead',         'kenji@titanrobotics.ai',    '+1 412-555-1014', 'https://linkedin.com/in/kenji-takahashi',  13, 6),
(15, 'Mrs.', 'Valerie', 'DuPont',     'VP Guest Experience',     'vdupont@pulsehospitality.com','+1 305-555-1015','https://linkedin.com/in/valerie-dupont',   14, 7),
(16, 'Mr.',  'Samuel',  'Altman',     'Chief Data Architect',    'samuel@quantumdata.ai',     '+1 415-555-1016', 'https://linkedin.com/in/samuel-altman',    15, 4),
(17, 'Ms.',  'Hanna',   'Lindqvist',  'Supply Director',         'hlind@silverlineauto.com',  '+1 313-555-1017', 'https://linkedin.com/in/hanna-lindqvist',  16, 5),
(18, 'Mr.',  'Arthur',  'Pendleton',  'VP Flight Avionics',      'arthur@astraea-aero.com',   '+1 303-555-1018', 'https://linkedin.com/in/arthur-pendleton', 17, 1),
(19, 'Dr.',  'Nadia',   'Hussain',    'Dean of Student Systems', 'nhussain@northstaredu.org', '+1 612-555-1019', 'https://linkedin.com/in/nadia-hussain',    18, 6),
(20, 'Mr.',  'Charles', 'Montgomery', 'Managing Director',       'cmont@crestviewcap.com',    '+1 212-555-1020', 'https://linkedin.com/in/charles-mont',     19, 7),
(21, 'Ms.',  'Rachel',  'Zane',       'General Counsel',         'rzane@veritaslegal.io',     '+1 202-555-1021', 'https://linkedin.com/in/rachel-zane',      20, 4),
(22, 'Mr.',  'Brandon', 'Walsh',      'VP Cold Chain Logistics', 'bwalsh@harborstorage.com',  '+1 912-555-1022', 'https://linkedin.com/in/brandon-walsh',    21, 5),
(23, 'Mrs.', 'Diane',   'Lockhart',   'Chief Claims Officer',    'dlockhart@elevateins.com',  '+1 860-555-1023', 'https://linkedin.com/in/diane-lockhart',   22, 1),
(24, 'Mr.',  'Naveen',  'Khurana',    'Deputy Director of IT',   'nkhurana@sunrisehealth.org','+1 415-555-1024', 'https://linkedin.com/in/naveen-khurana',   1,  1),
(25, 'Ms.',  'Tanya',   'Brooks',     'Senior Buyer',            'tbrooks@omniretail.com',    '+1 206-555-1025', 'https://linkedin.com/in/tanya-brooks',     11, 5)
ON CONFLICT (id) DO NOTHING;

-- 4. LEADS (25 Leads covering ALL stages, sources, campaign statuses, and upload states)
INSERT INTO leads (
  id, salutation, first_name, last_name, company, title, industry, email, phone, 
  linkedin_url, company_website, company_linkedin_url, annual_revenue, employees, location,
  untouched, uploaded_from, source, stage, demo_date, lost_reason, lost_notes,
  unqualified_reason, unqualified_notes, revisit_date, revisit_reason,
  converted_at, closed_at, email_invalid_at, email_invalid_reason, unsubscribed_at, owner_id, created_at
) VALUES
-- STAGE: New (4 leads, different sources, untouched states)
(1, 'Mr.', 'Vikram', 'Singh', 'BrightPath Schools', 'Principal', 'Education', 'vikram@brightpath.in', '+1 415-555-2001',
 'https://linkedin.com/in/vikram-singh', 'brightpath.in', 'https://linkedin.com/company/brightpath', 3500000.00, 85, 'San Francisco, CA',
 FALSE, NULL, 'Website', 'New', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, NOW() - INTERVAL '2 days'),

(2, 'Ms.', 'Neha', 'Gupta', 'UrbanNest Realty', 'VP of Sales', 'Real Estate', 'neha@urbannest.in', '+1 212-555-2002',
 'https://linkedin.com/in/neha-gupta', 'urbannest.in', 'https://linkedin.com/company/urbannest', 5200000.00, 110, 'New York, NY',
 TRUE, 'q1_inbound_leads.xlsx', 'Upload', 'New', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 4, NOW() - INTERVAL '1 day'),

(3, 'Mr.', 'Daniel', 'Kim', 'Apex BioSystems', 'Lab Director', 'Healthcare', 'dkim@apexbiosys.com', '+1 617-555-2003',
 'https://linkedin.com/in/daniel-kim-bio', 'apexbiosys.com', 'https://linkedin.com/company/apexbiosys', 11000000.00, 240, 'Boston, MA',
 FALSE, NULL, 'Event', 'New', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5, NOW() - INTERVAL '4 hours'),

(4, 'Mrs.', 'Jessica', 'Alba', 'Honest Logistics', 'Chief Logistics Officer', 'Logistics', 'jalba@honestlogistics.com', '+1 312-555-2004',
 'https://linkedin.com/in/jessica-alba-log', 'honestlogistics.com', 'https://linkedin.com/company/honestlogistics', 8000000.00, 190, 'Chicago, IL',
 FALSE, NULL, 'Social Media', 'New', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 6, NOW() - INTERVAL '5 hours'),

-- STAGE: Nurturing (4 leads, active engagement)
(5, 'Mr.', 'Travis', 'Kalanick', 'MetroFleet Technologies', 'CEO', 'Transportation', 'travis@metrofleet.com', '+1 415-555-2005',
 'https://linkedin.com/in/travis-metro', 'metrofleet.com', 'https://linkedin.com/company/metrofleet', 24000000.00, 480, 'San Francisco, CA',
 FALSE, NULL, 'Referral', 'Nurturing', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, NOW() - INTERVAL '10 days'),

(6, 'Ms.', 'Rachel', 'Green', 'Central Perk Retail', 'Director of Buying', 'Retail', 'rgreen@centralperk.com', '+1 212-555-2006',
 'https://linkedin.com/in/rachel-green-retail', 'centralperk.com', 'https://linkedin.com/company/centralperk', 4500000.00, 75, 'New York, NY',
 FALSE, NULL, 'Phone', 'Nurturing', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 4, NOW() - INTERVAL '8 days'),

(7, 'Dr.', 'Aris', 'Thorne', 'Nexus Genomics', 'VP Scientific Computing', 'Biotechnology', 'athorne@nexusgenomics.com', '+1 617-555-2007',
 'https://linkedin.com/in/aris-thorne', 'nexusgenomics.com', 'https://linkedin.com/company/nexusgenomics', 16000000.00, 320, 'Cambridge, MA',
 FALSE, NULL, 'Email', 'Nurturing', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5, NOW() - INTERVAL '12 days'),

(8, 'Mr.', 'Gareth', 'Bale', 'Peak Performance Labs', 'Head of Athletic Tech', 'Sports Tech', 'gbale@peakperformance.com', '+1 512-555-2008',
 'https://linkedin.com/in/gareth-bale-peak', 'peakperformance.com', 'https://linkedin.com/company/peakperformance', 7000000.00, 130, 'Austin, TX',
 FALSE, NULL, 'Website', 'Nurturing', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 7, NOW() - INTERVAL '6 days'),

-- STAGE: Demo (4 leads: 2 upcoming demos, 2 recently conducted)
(9, 'Mr.', 'Rohit', 'Verma', 'CloudKart eCommerce', 'CTO', 'E-commerce', 'rohit@cloudkart.in', '+1 408-555-2009',
 'https://linkedin.com/in/rohit-verma-cloud', 'cloudkart.in', 'https://linkedin.com/company/cloudkart', 32000000.00, 650, 'San Jose, CA',
 FALSE, NULL, 'Event', 'Demo', NOW() + INTERVAL '1 day 3 hours', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, NOW() - INTERVAL '14 days'),

(10, 'Ms.', 'Claire', 'Underwood', 'Capitol Defense Systems', 'VP Strategy', 'Aerospace', 'cunderwood@capitoldefense.com', '+1 202-555-2010',
 'https://linkedin.com/in/claire-underwood', 'capitoldefense.com', 'https://linkedin.com/company/capitoldefense', 55000000.00, 980, 'Washington, DC',
 FALSE, NULL, 'Referral', 'Demo', NOW() + INTERVAL '3 days', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 6, NOW() - INTERVAL '18 days'),

(11, 'Mr.', 'Gordon', 'Gekko', 'WallStreet Algorithms', 'Managing Partner', 'Finance', 'ggekko@wallstreetalgo.com', '+1 212-555-2011',
 'https://linkedin.com/in/gordon-gekko-algo', 'wallstreetalgo.com', 'https://linkedin.com/company/wallstreetalgo', 42000000.00, 410, 'New York, NY',
 FALSE, NULL, 'Website', 'Demo', NOW() - INTERVAL '1 day', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 4, NOW() - INTERVAL '15 days'),

(12, 'Dr.', 'Sheldon', 'Cooper', 'CalTech Physics Tools', 'Lead Researcher', 'Education', 'scooper@caltechtools.org', '+1 626-555-2012',
 'https://linkedin.com/in/sheldon-cooper-phd', 'caltechtools.org', 'https://linkedin.com/company/caltechtools', 8900000.00, 160, 'Pasadena, CA',
 FALSE, NULL, 'Other', 'Demo', NOW() - INTERVAL '4 hours', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5, NOW() - INTERVAL '9 days'),

-- STAGE: Revisit (3 leads: future revisit date and clear reason)
(13, 'Mr.', 'Bruce', 'Wayne', 'Gotham Security Tech', 'Chairman', 'Security', 'bwayne@gothamtech.com', '+1 312-555-2013',
 'https://linkedin.com/in/bruce-wayne-tech', 'gothamtech.com', 'https://linkedin.com/company/gothamtech', 95000000.00, 2200, 'Chicago, IL',
 FALSE, NULL, 'Event', 'Revisit', NULL, NULL, NULL, NULL, NULL, NOW() + INTERVAL '25 days', 'Waiting for Q3 budget', NULL, NULL, NULL, NULL, NULL, 1, NOW() - INTERVAL '20 days'),

(14, 'Ms.', 'Peggy', 'Olson', 'Sterling Cooper AdTech', 'Head of Copy', 'Media', 'polson@sterlingadtech.com', '+1 212-555-2014',
 'https://linkedin.com/in/peggy-olson', 'sterlingadtech.com', 'https://linkedin.com/company/sterlingadtech', 14000000.00, 275, 'New York, NY',
 FALSE, NULL, 'Social Media', 'Revisit', NULL, NULL, NULL, NULL, NULL, NOW() + INTERVAL '12 days', 'Vendor contract ending soon', NULL, NULL, NULL, NULL, NULL, 4, NOW() - INTERVAL '22 days'),

(15, 'Mr.', 'Logan', 'Roy', 'Waystar Modern Broadcast', 'Executive Chairman', 'Media', 'lroy@waystarmodern.com', '+1 212-555-2015',
 'https://linkedin.com/in/logan-roy-waystar', 'waystarmodern.com', 'https://linkedin.com/company/waystar', 85000000.00, 3400, 'New York, NY',
 FALSE, NULL, 'Phone', 'Revisit', NULL, NULL, NULL, NULL, NULL, NOW() + INTERVAL '45 days', 'Internal restructuring', NULL, NULL, NULL, NULL, NULL, 6, NOW() - INTERVAL '30 days'),

-- STAGE: Unqualified (4 leads: covering different unqualified reasons)
(16, 'Mr.', 'Peter', 'Parker', 'Daily Bugle Press', 'Freelance Tech Reviewer', 'Media', 'pparker@dailybugle.com', '+1 212-555-2016',
 'https://linkedin.com/in/peter-parker-photo', 'dailybugle.com', 'https://linkedin.com/company/dailybugle', 1200000.00, 18, 'New York, NY',
 FALSE, NULL, 'Website', 'Unqualified', NULL, NULL, NULL, 'No budget', 'Company revenue under $2M threshold; no CRM budget', NULL, NULL, NULL, NOW() - INTERVAL '4 days', NULL, NULL, NULL, 1, NOW() - INTERVAL '15 days'),

(17, 'Ms.', 'Pamela', 'Beesly', 'Dunder Mifflin Paper Co', 'Office Administrator', 'Manufacturing', 'pbeesly@dundermifflin.com', '+1 570-555-2017',
 'https://linkedin.com/in/pam-beesly', 'dundermifflin.com', 'https://linkedin.com/company/dundermifflin', 6000000.00, 45, 'Scranton, PA',
 FALSE, NULL, 'Phone', 'Unqualified', NULL, NULL, NULL, 'No authority', 'User is evaluating on their own; no executive sponsor', NULL, NULL, NULL, NOW() - INTERVAL '6 days', NULL, NULL, NULL, 5, NOW() - INTERVAL '19 days'),

(18, 'Mr.', 'Dwight', 'Schrute', 'Schrute Beet Farms', 'Owner & Operator', 'Agriculture', 'dschrute@schrutebeetfarms.com', '+1 570-555-2018',
 'https://linkedin.com/in/dwight-schrute', 'schrutebeetfarms.com', 'https://linkedin.com/company/schrutebeetfarms', 850000.00, 12, 'Honesdale, PA',
 FALSE, NULL, 'Referral', 'Unqualified', NULL, NULL, NULL, 'Not a fit', 'Sole proprietorship with 12 farm hands; requires agri-inventory, not sales CRM', NULL, NULL, NULL, NOW() - INTERVAL '10 days', NULL, NULL, NULL, 7, NOW() - INTERVAL '25 days'),

(19, 'Mr.', 'Barney', 'Stinson', 'GNB Consulting Group', 'VP of Acquisitions', 'Finance', 'bstinson@gnbcorp.com', '+1 212-555-2019',
 'https://linkedin.com/in/barney-stinson', 'gnbcorp.com', 'https://linkedin.com/company/gnbcorp', 40000000.00, 900, 'New York, NY',
 FALSE, NULL, 'Event', 'Unqualified', NULL, NULL, NULL, 'Bad timing', 'Company is being acquired next quarter', NULL, NULL, NULL, NOW() - INTERVAL '3 days', NULL, NULL, NULL, 4, NOW() - INTERVAL '14 days'),

-- STAGE: Lost (3 leads: covering different lost reasons)
(20, 'Ms.', 'Pooja', 'Joshi', 'FreshMart Grocers', 'Store Operations Director', 'Retail', 'pooja@freshmart.in', '+1 415-555-2020',
 'https://linkedin.com/in/pooja-joshi', 'freshmart.in', 'https://linkedin.com/company/freshmart', 7800000.00, 170, 'San Francisco, CA',
 FALSE, NULL, 'Phone', 'Lost', NULL, 'No response', 'No response after 4 calls, 2 voicemails, and 3 follow-up emails', NULL, NULL, NULL, NULL, NULL, NOW() - INTERVAL '5 days', NULL, NULL, NULL, 1, NOW() - INTERVAL '24 days'),

(21, 'Mr.', 'Walter', 'White', 'BlueSky Chemical Solutions', 'Chief Chemist', 'Chemicals', 'wwhite@blueskychem.com', '+1 505-555-2021',
 'https://linkedin.com/in/walter-white-chem', 'blueskychem.com', 'https://linkedin.com/company/blueskychem', 15000000.00, 80, 'Albuquerque, NM',
 FALSE, NULL, 'Website', 'Lost', NULL, 'Competitor', 'Signed a multi-year deal with Salesforce Enterprise', NULL, NULL, NULL, NULL, NULL, NOW() - INTERVAL '8 days', NULL, NULL, NULL, 6, NOW() - INTERVAL '28 days'),

(22, 'Mr.', 'Jesse', 'Pinkman', 'Vamonos Pest Control', 'COO', 'Services', 'jpinkman@vamonospest.com', '+1 505-555-2022',
 'https://linkedin.com/in/jesse-pinkman', 'vamonospest.com', 'https://linkedin.com/company/vamonospest', 3100000.00, 42, 'Albuquerque, NM',
 FALSE, NULL, 'Email', 'Lost', NULL, 'Price', 'Budget capped at $15k/year; our quote was $28k/year', NULL, NULL, NULL, NULL, NULL, NOW() - INTERVAL '11 days', NULL, NULL, NULL, 7, NOW() - INTERVAL '35 days'),

-- STAGE: Converted (leads that graduated to Opportunities 1 to 4)
(23, 'Dr.', 'Meera', 'Iyer', 'Sunrise Health Systems', 'Director of Operations', 'Healthcare', 'meera@sunrisehealth.org', '+1 415-555-1001',
 'https://linkedin.com/in/meera-iyer', 'sunrisehealth.org', 'https://linkedin.com/company/sunrise-health', 15000000.00, 450, 'San Francisco, CA',
 FALSE, NULL, 'Referral', 'Converted', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NOW() - INTERVAL '40 days', NULL, NULL, NULL, NULL, 1, NOW() - INTERVAL '60 days'),

(24, 'Mr.', 'Arjun', 'Mehta', 'GreenLeaf Organics', 'VP of Supply Chain', 'FMCG', 'arjun@greenleaforganics.com', '+1 212-555-1003',
 'https://linkedin.com/in/arjun-mehta', 'greenleaforganics.com', 'https://linkedin.com/company/greenleaf-organics', 8500000.00, 180, 'New York, NY',
 FALSE, NULL, 'Website', 'Converted', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NOW() - INTERVAL '30 days', NULL, NULL, NULL, NULL, 4, NOW() - INTERVAL '50 days'),

(25, 'Ms.', 'Kavya', 'Reddy', 'Apex Freight Logistics', 'COO & Head of Logistics', 'Logistics', 'kavya@apexlogistics.io', '+1 312-555-1004',
 'https://linkedin.com/in/kavya-reddy', 'apexlogistics.io', 'https://linkedin.com/company/apex-logistics', 24000000.00, 620, 'Chicago, IL',
 FALSE, NULL, 'Event', 'Converted', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NOW() - INTERVAL '20 days', NULL, NULL, NULL, NULL, 5, NOW() - INTERVAL '45 days'),

-- Lead with email campaign conditions: Invalid Email & Unsubscribed
(26, 'Mr.', 'Arthur', 'Dent', 'Hitchhiker Travel Co', 'Travel Coordinator', 'Hospitality', 'adent@hitchhikertravel.com', '+1 415-555-2026',
 'https://linkedin.com/in/arthur-dent', 'hitchhikertravel.com', 'https://linkedin.com/company/hitchhikertravel', 4200000.00, 65, 'San Francisco, CA',
 FALSE, NULL, 'Website', 'Nurturing', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NOW() - INTERVAL '2 days', '550 5.1.1 User unknown / Mailbox does not exist', NULL, 1, NOW() - INTERVAL '15 days'),

(27, 'Ms.', 'Trillian', 'Astra', 'Galaxy Tech Systems', 'Lead Astrophysicist', 'Technology', 'trillian@galaxytech.io', '+1 408-555-2027',
 'https://linkedin.com/in/trillian-astra', 'galaxytech.io', 'https://linkedin.com/company/galaxytech', 19000000.00, 310, 'San Jose, CA',
 FALSE, NULL, 'Event', 'Nurturing', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NOW() - INTERVAL '3 days', 4, NOW() - INTERVAL '20 days')
ON CONFLICT (id) DO NOTHING;

-- 5. OPPORTUNITIES (22 Deals across all 5 stages: Opportunity, Discovery, Proposal, Won, Lost)
INSERT INTO opportunities (
  id, name, stage, probability, expected_value, final_value, expected_close_date,
  lost_reason, lost_notes, discovery_needs, discovery_budget, discovery_decision_maker, discovery_timeline,
  closed_at, account_id, primary_contact_id, lead_id, owner_id, created_at
) VALUES
-- STAGE: Opportunity (20% probability - 5 deals)
(1, 'Sunrise Health - EHR Mobile CRM Extension', 'Opportunity', 20, 185000.00, NULL, CURRENT_DATE + 45,
 NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, 1, 23, 1, NOW() - INTERVAL '40 days'),

(2, 'CloudPulse - 2,000 Seat Enterprise Migration', 'Opportunity', 20, 450000.00, NULL, CURRENT_DATE + 60,
 NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5, 6, NULL, 4, NOW() - INTERVAL '15 days'),

(3, 'Beacon Media - Digital Ad Sales CRM', 'Opportunity', 20, 95000.00, NULL, CURRENT_DATE + 35,
 NULL, NULL, NULL, NULL, NULL, NULL, NULL, 7, 8, NULL, 5, NOW() - INTERVAL '12 days'),

(4, 'Titan Robotics - Factory Sales Portal', 'Opportunity', 20, 320000.00, NULL, CURRENT_DATE + 75,
 NULL, NULL, NULL, NULL, NULL, NULL, NULL, 13, 14, NULL, 6, NOW() - INTERVAL '18 days'),

(5, 'NorthStar Edu - Campus Lead Tracking', 'Opportunity', 20, 80000.00, NULL, CURRENT_DATE + 50,
 NULL, NULL, NULL, NULL, NULL, NULL, NULL, 18, 19, NULL, 7, NOW() - INTERVAL '8 days'),

-- STAGE: Discovery (40% probability - 5 deals, includes discovery fields)
(6, 'GreenLeaf - B2B Distributor Portal', 'Discovery', 40, 240000.00, NULL, CURRENT_DATE + 30,
 NULL, NULL, 'Needs integration with SAP ECC and real-time inventory checks for 400 retailers', '$200k - $250k', 'Arjun Mehta (VP Supply Chain) & Board', 'Q3 rollout before holiday season', NULL, 2, 3, 24, 4, NOW() - INTERVAL '30 days'),

(7, 'Zenith Solar - Commercial Installer Pipeline', 'Discovery', 40, 380000.00, NULL, CURRENT_DATE + 40,
 NULL, NULL, 'Field quote generation on iPads with offline sync capability', '$350k approved in 2026 CapEx', 'David Sterling (VP Clean Grid)', 'Targeting go-live in 4 months', NULL, 8, 9, NULL, 7, NOW() - INTERVAL '22 days'),

(8, 'OmniRetail - OmniChannel Customer Tracking', 'Discovery', 40, 520000.00, NULL, CURRENT_DATE + 55,
 NULL, NULL, 'Unify in-store POS loyalty data with online Shopify store leads', '$500k allocated', 'Sophia Martinez (Head of Digital)', 'Phased launch starting August', NULL, 11, 12, NULL, 5, NOW() - INTERVAL '25 days'),

(9, 'Pulse Hospitality - VIP Booking Concierge CRM', 'Discovery', 40, 160000.00, NULL, CURRENT_DATE + 25,
 NULL, NULL, 'Automated SMS & WhatsApp welcome alerts for 14 luxury resort locations', '$150k - $175k', 'Valerie DuPont (VP Guest Exp)', '60 days', NULL, 14, 15, NULL, 7, NOW() - INTERVAL '16 days'),

(10, 'Quantum Data - AI Model Sales Management', 'Discovery', 40, 750000.00, NULL, CURRENT_DATE + 45,
 NULL, NULL, 'Custom CPQ pricing engine for compute cluster token consumption', '$700k - $800k', 'Samuel Altman (Chief Data Architect) & CFO', 'End of Q3', NULL, 15, 16, NULL, 4, NOW() - INTERVAL '28 days'),

-- STAGE: Proposal (75% probability - 5 deals)
(11, 'Vanguard FinTech - Wealth Manager Suite', 'Proposal', 75, 820000.00, NULL, CURRENT_DATE + 14,
 NULL, NULL, 'Full compliance with SEC & FINRA audit trail rules; dual-signoff workflows', '$800k+', 'Jonathan Drake (Head of Risk) & Legal', 'Immediate once contract signed', NULL, 6, 7, NULL, 1, NOW() - INTERVAL '35 days'),

(12, 'Aegis Cyber - Threat Intelligence Deal Desk', 'Proposal', 75, 290000.00, NULL, CURRENT_DATE + 10,
 NULL, NULL, 'Automated quotation for government defense contractors with FedRAMP compliance', '$300k', 'Dr. Amara Okafor (CSO)', 'Within 30 days', NULL, 9, 10, NULL, 6, NOW() - INTERVAL '26 days'),

(13, 'BlueRidge Gear - Heavy Equipment Fleet Renewal', 'Proposal', 75, 410000.00, NULL, CURRENT_DATE + 18,
 NULL, NULL, 'Telematics GPS sync with maintenance alerts and dealer trade-in valuations', '$400k', 'Robert MacKenzie (Fleet Dir)', '3 weeks', NULL, 10, 11, NULL, 4, NOW() - INTERVAL '32 days'),

(14, 'Summit BioLabs - Clinical Trials Participant CRM', 'Proposal', 75, 340000.00, NULL, CURRENT_DATE + 21,
 NULL, NULL, 'HIPAA compliant patient enrollment and automated consent form signing', '$350k', 'Dr. Gregory House', 'May 2026', NULL, 12, 13, NULL, 1, NOW() - INTERVAL '29 days'),

(15, 'Silverline Automotive - Global Dealer Network', 'Proposal', 75, 680000.00, NULL, CURRENT_DATE + 15,
 NULL, NULL, 'Multi-currency invoicing across 220 international dealerships', '$650k - $700k', 'Hanna Lindqvist (Supply Dir)', 'Q2 end', NULL, 16, 17, NULL, 5, NOW() - INTERVAL '38 days'),

-- STAGE: Won (100% probability - 4 closed won deals with final_value and closed_at)
(16, 'Apex Logistics - Global Fleet Telematics CRM', 'Won', 100, 700000.00, 685000.00, CURRENT_DATE - 5,
 NULL, NULL, 'Enterprise routing and driver dispatch tracking', '$700k', 'Kavya Reddy (COO)', 'Immediate', NOW() - INTERVAL '5 days', 3, 4, 25, 5, NOW() - INTERVAL '50 days'),

(17, 'Astraea Aerospace - Satellite Ground Ops CRM', 'Won', 100, 1250000.00, 1250000.00, CURRENT_DATE - 12,
 NULL, NULL, 'Secure mission data logging and contractor parts clearance', '$1.25M', 'Arthur Pendleton (VP Avionics)', 'Q1 launch', NOW() - INTERVAL '12 days', 17, 18, NULL, 1, NOW() - INTERVAL '75 days'),

(18, 'Crestview Capital - Private Equity Deal Pipeline', 'Won', 100, 950000.00, 920000.00, CURRENT_DATE - 20,
 NULL, NULL, 'M&A deal screening and investor data room analytics', '$1M', 'Charles Montgomery (Managing Dir)', 'February 2026', NOW() - INTERVAL '20 days', 19, 20, NULL, 7, NOW() - INTERVAL '90 days'),

(19, 'Elevate Insurance - Automated Claims Dispatch', 'Won', 100, 580000.00, 560000.00, CURRENT_DATE - 2,
 NULL, NULL, 'Instant catastrophic storm claims adjuster routing', '$600k', 'Diane Lockhart (Chief Claims Officer)', 'Immediate', NOW() - INTERVAL '2 days', 22, 23, NULL, 1, NOW() - INTERVAL '45 days'),

-- STAGE: Lost (0% probability - 3 closed lost deals with lost_reason and lost_notes)
(20, 'Nova Textiles - Dealer eCommerce Portal', 'Lost', 0, 500000.00, NULL, CURRENT_DATE - 14,
 'Competitor', 'Customer chose a specialized local European vendor who provided on-premise hosting.',
 'Legacy ERP connector and fabric swatch sample requests', '$450k', 'Sanjay Patel (Dir Procurement)', 'Immediate',
 NOW() - INTERVAL '14 days', 4, 5, NULL, 6, NOW() - INTERVAL '65 days'),

(21, 'Veritas Legal - Case Intake Management System', 'Lost', 0, 220000.00, NULL, CURRENT_DATE - 8,
 'Price', 'Board declined the budget; decided to stick to existing manual spreadsheet workflows.',
 'Clio and NetDocuments document management synchronization', '$150k max', 'Rachel Zane (General Counsel)', 'Immediate',
 NOW() - INTERVAL '8 days', 20, 21, NULL, 4, NOW() - INTERVAL '40 days'),

(22, 'Harbor Cold Storage - Warehouse Billing Engine', 'Lost', 0, 310000.00, NULL, CURRENT_DATE - 25,
 'No budget', 'CFO froze all non-essential software investments following port tariff disputes.',
 'Refrigerated container dwell-time billing calculation', '$300k', 'Brandon Walsh (VP Logistics)', 'Q1',
 NOW() - INTERVAL '25 days', 21, 22, NULL, 5, NOW() - INTERVAL '70 days')
ON CONFLICT (id) DO NOTHING;

-- 6. TASKS (25 Tasks covering Overdue, Due Today, Due Tomorrow, Upcoming, Open, Done, Auto-closed)
INSERT INTO tasks (
  id, title, description, due_date, reminder_at, status, priority, is_auto, completed_at, owner_id, lead_id, opportunity_id
) VALUES
-- OVERDUE TASKS (Status = Open, due in the past) -> Highlights in Red / Alerts
(1,  'Call Neha Gupta regarding Q1 property rollout', 'Review custom MLS integration options before pricing meeting',
     NOW() - INTERVAL '3 days', NOW() - INTERVAL '4 days', 'Open', 'High', FALSE, NULL, 1, 2, NULL),

(2,  'Send revised NDA to MetroFleet CEO', 'Legal redlined section 4 on proprietary telemetry IP',
     NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days 4 hours', 'Open', 'High', FALSE, NULL, 4, 5, NULL),

(3,  'Follow up on Discovery notes for Zenith Solar', 'Clarify solar array monitoring inverter models',
     NOW() - INTERVAL '1 day 5 hours', NULL, 'Open', 'Normal', TRUE, NULL, 7, NULL, 7),

(4,  'Audit BlueRidge Gear equipment telemetry schema', 'Ensure ISO 15143-3 machinery standard compatibility',
     NOW() - INTERVAL '5 days', NULL, 'Open', 'Low', FALSE, NULL, 4, NULL, 13),

-- DUE TODAY TASKS (Status = Open, due today) -> Shows on Dashboard "Today's Tasks" widget
(5,  'Make first contact with Vikram Singh', 'Call BrightPath Schools regarding student admissions pipeline',
     CURRENT_DATE + INTERVAL '16 hours', CURRENT_DATE + INTERVAL '15 hours', 'Open', 'High', TRUE, NULL, 1, 1, NULL),

(6,  'Conduct live product demo for CloudKart', 'Deep dive into cart abandonment triggers and high-volume checkout latency',
     CURRENT_DATE + INTERVAL '14 hours', CURRENT_DATE + INTERVAL '13 hours', 'Open', 'High', TRUE, NULL, 1, 9, NULL),

(7,  'Deliver proposal pricing breakdown to Vanguard FinTech', 'Include Tier-1 dedicated cloud hosting options and SLA guarantees',
     CURRENT_DATE + INTERVAL '17 hours', CURRENT_DATE + INTERVAL '16 hours', 'Open', 'High', FALSE, NULL, 1, NULL, 11),

(8,  'Weekly sales pipeline alignment meeting', 'Review team progress against Q2 monthly quota targets',
     CURRENT_DATE + INTERVAL '11 hours', NULL, 'Open', 'Normal', FALSE, NULL, 2, NULL, NULL),

(9,  'Verify security compliance docs for Aegis Cyber', 'Attach SOC-2 Type II report to deal desk ticket',
     CURRENT_DATE + INTERVAL '18 hours', CURRENT_DATE + INTERVAL '17 hours', 'Open', 'Normal', FALSE, NULL, 6, NULL, 12),

-- UPCOMING TASKS (Due tomorrow and in future days)
(10, 'Prepare onboarding kickoff for Elevate Insurance', 'Schedule technical architecture review with claims engineering team',
     CURRENT_DATE + INTERVAL '2 days 10 hours', CURRENT_DATE + INTERVAL '2 days 9 hours', 'Open', 'High', FALSE, NULL, 1, NULL, 19),

(11, 'Prepare demo deck for Capitol Defense Systems', 'Focus on role-based security permissions and air-gapped deployments',
     CURRENT_DATE + INTERVAL '3 days 14 hours', NULL, 'Open', 'Normal', TRUE, NULL, 6, 10, NULL),

(12, 'Review customer feedback with GreenLeaf VP', 'Review user feedback on the supplier mobile interface wireframes',
     CURRENT_DATE + INTERVAL '4 days 15 hours', CURRENT_DATE + INTERVAL '4 days 14 hours', 'Open', 'Normal', FALSE, NULL, 4, NULL, 6),

(13, 'Follow up with Bruce Wayne on Q3 CapEx budget', 'Check if board approved the enterprise physical security software spend',
     CURRENT_DATE + INTERVAL '25 days', NULL, 'Open', 'Normal', TRUE, NULL, 1, 13, NULL),

(14, 'Finalize Silverline Automotive dealer SLA', 'Review international multi-language localization requirements',
     CURRENT_DATE + INTERVAL '5 days 12 hours', NULL, 'Open', 'Normal', FALSE, NULL, 5, NULL, 15),

(15, 'Schedule quarterly check-in with Apex Logistics', 'Review fleet telematics uptime and driver adoption metrics',
     CURRENT_DATE + INTERVAL '15 days', NULL, 'Open', 'Low', FALSE, NULL, 5, NULL, 16),

-- COMPLETED TASKS (Status = Done, completed_at is set)
(16, 'Send initial product overview deck to CloudPulse', 'Emailed solution architecture whitepaper to Elena Rostova',
     NOW() - INTERVAL '14 days', NULL, 'Done', 'Normal', TRUE, NOW() - INTERVAL '14 days 2 hours', 4, NULL, 2),

(17, 'Discovery call with OmniRetail team', 'Completed 45 min requirements gathering session with Sophia Martinez',
     NOW() - INTERVAL '24 days', NULL, 'Done', 'High', FALSE, NOW() - INTERVAL '24 days', 5, NULL, 8),

(18, 'Deliver formal contract to Astraea Aerospace', 'Delivered signed Master Services Agreement and SOW to legal counsel',
     NOW() - INTERVAL '13 days', NULL, 'Done', 'High', FALSE, NOW() - INTERVAL '13 days 3 hours', 1, NULL, 17),

(19, 'Send security whitepaper to Dr. Okafor', 'Emailed ISO 27001 certificate and penetration test summary',
     NOW() - INTERVAL '20 days', NULL, 'Done', 'Normal', TRUE, NOW() - INTERVAL '20 days 1 hour', 6, NULL, 12),

(20, 'Initial discovery call with Crestview Capital', 'Discussed private equity screening workflow and deal metrics',
     NOW() - INTERVAL '80 days', NULL, 'Done', 'Normal', FALSE, NOW() - INTERVAL '80 days', 7, NULL, 18),

-- AUTO-CLOSED TASKS (Status = Auto-closed by system when stage moved forward)
(21, 'Make first contact with Dr. Meera Iyer', 'System closed task upon converting lead to opportunity',
     NOW() - INTERVAL '40 days', NULL, 'Auto-closed', 'Normal', TRUE, NOW() - INTERVAL '40 days', 1, 23, NULL),

(22, 'Follow up call on FreshMart trial', 'System auto-closed when lead marked as Lost (No response)',
     NOW() - INTERVAL '6 days', NULL, 'Auto-closed', 'Normal', TRUE, NOW() - INTERVAL '5 days', 1, 20, NULL),

(23, 'Follow up on proposal for Nova Textiles', 'System auto-closed when deal marked as Lost to competitor',
     NOW() - INTERVAL '15 days', NULL, 'Auto-closed', 'Normal', TRUE, NOW() - INTERVAL '14 days', 6, NULL, 20),

(24, 'Make first contact with Arjun Mehta', 'Auto-closed upon conversion to GreenLeaf deal',
     NOW() - INTERVAL '30 days', NULL, 'Auto-closed', 'Normal', TRUE, NOW() - INTERVAL '30 days', 4, 24, NULL),

(25, 'Make first contact with Kavya Reddy', 'Auto-closed upon conversion to Apex Logistics opportunity',
     NOW() - INTERVAL '20 days', NULL, 'Auto-closed', 'Normal', TRUE, NOW() - INTERVAL '20 days', 5, 25, NULL)
ON CONFLICT (id) DO NOTHING;

-- 7. NOTES (Rich meeting & deal activity history)
INSERT INTO notes (id, body, created_by_id, lead_id, opportunity_id, created_at) VALUES
(1,  'Call notes: Principal Vikram Singh is looking for a cloud solution to track student admissions across 3 campuses. Highly interested in parent notification features.',
     1, 1, NULL, NOW() - INTERVAL '2 days'),

(2,  'Left voicemail for Neha Gupta. UrbanNest is planning to onboard 40 new real estate agents next month and wants automated commission splitting.',
     4, 2, NULL, NOW() - INTERVAL '1 day'),

(3,  'Technical discovery call with CloudKart CTO Rohit Verma: They process 12,000 orders/day during flash sales. Needs sub-50ms API response time.',
     1, 9, NULL, NOW() - INTERVAL '13 days'),

(4,  'Revisit scheduled for Bruce Wayne. Wayne Tech has frozen software purchasing until their new fiscal year begins in October.',
     1, 13, NULL, NOW() - INTERVAL '20 days'),

(5,  'Unqualified reason: Spoke with Pam Beesly at Dunder Mifflin. Only looking for free personal templates, no corporate procurement authorization.',
     5, 17, NULL, NOW() - INTERVAL '6 days'),

(6,  'Executive presentation with Vanguard FinTech: CFO and Chief Risk Officer attended. Emphasized our end-to-end data encryption and role-based ACLs.',
     1, NULL, 11, NOW() - INTERVAL '32 days'),

(7,  'Pricing negotiation with BlueRidge Heavy Gear: Offered 8% multi-year discount if payment is settled annually upfront.',
     4, NULL, 13, NOW() - INTERVAL '25 days'),

(8,  'Final contract signed by Astraea Aerospace! $1.25M ACV for 3-year term. Onboarding begins next Monday with the mission support team.',
     1, NULL, 17, NOW() - INTERVAL '12 days'),

(9,  'Deal closed won: Elevate Insurance selected us over Guidewire for their rapid mobile claims adjuster dispatch module.',
     1, NULL, 19, NOW() - INTERVAL '2 days'),

(10, 'Competitor debrief: Nova Textiles selected a local vendor who offered on-premise installation on their local server room.',
     6, NULL, 20, NOW() - INTERVAL '14 days')
ON CONFLICT (id) DO NOTHING;

-- 8. STAGE_HISTORY (Audit trail of pipeline progression)
INSERT INTO stage_history (from_stage, to_stage, note, changed_at, changed_by_id, lead_id, opportunity_id) VALUES
-- Lead 1: New
(NULL,        'New',         'Lead created via website form inquiry', NOW() - INTERVAL '2 days', 1, 1, NULL),
-- Lead 5: New -> Nurturing
(NULL,        'New',         'Lead created via partner referral', NOW() - INTERVAL '10 days', 1, 5, NULL),
('New',       'Nurturing',   'Qualified initial interest, requested product overview', NOW() - INTERVAL '7 days', 1, 5, NULL),
-- Lead 9: New -> Nurturing -> Demo
(NULL,        'New',         'Met at Cloud Expo 2026', NOW() - INTERVAL '14 days', 1, 9, NULL),
('New',       'Nurturing',   'Sent whitepaper and confirmed target architecture', NOW() - INTERVAL '11 days', 1, 9, NULL),
('Nurturing', 'Demo',        'Scheduled in-depth technical demo for engineering team', NOW() - INTERVAL '3 days', 1, 9, NULL),
-- Lead 20: Lost
(NULL,        'New',         'Inbound inquiry via phone', NOW() - INTERVAL '24 days', 1, 20, NULL),
('New',       'Nurturing',   'Attempted multiple follow-up calls', NOW() - INTERVAL '15 days', 1, 20, NULL),
('Nurturing', 'Lost',        'Unresponsive after 4 calls and 3 emails', NOW() - INTERVAL '5 days', 1, 20, NULL),
-- Opportunity 11: Opportunity -> Discovery -> Proposal
(NULL,        'Opportunity', 'Deal created from inbound enterprise inquiry', NOW() - INTERVAL '35 days', 1, NULL, 11),
('Opportunity','Discovery',  'Completed security and architecture review with risk committee', NOW() - INTERVAL '28 days', 1, NULL, 11),
('Discovery', 'Proposal',    'Sent comprehensive master service agreement and custom quotation', NOW() - INTERVAL '10 days', 1, NULL, 11),
-- Opportunity 17: Opportunity -> Discovery -> Proposal -> Won
(NULL,        'Opportunity', 'Inbound aerospace project requirement', NOW() - INTERVAL '75 days', 1, NULL, 17),
('Opportunity','Discovery',  'Detailed avionics data compliance audit passed', NOW() - INTERVAL '55 days', 1, NULL, 17),
('Discovery', 'Proposal',    'Submitted RFP response and pricing schedule', NOW() - INTERVAL '30 days', 1, NULL, 17),
('Proposal',  'Won',         'Contract fully executed by executive committee', NOW() - INTERVAL '12 days', 1, NULL, 17);

-- 9. NOTIFICATIONS (Bell icon alerts: unread & read)
INSERT INTO notifications (id, user_id, task_id, title, message, link, kind, is_read, created_at) VALUES
(1, 1, 1, 'Task overdue', 'Follow up with Neha Gupta was due 3 days ago', '/tasks', 'reminder', FALSE, NOW() - INTERVAL '3 days'),
(2, 1, 5, 'Task due today', 'Make first contact with Vikram Singh', '/leads/1', 'reminder', FALSE, NOW() - INTERVAL '2 hours'),
(3, 1, 6, 'Demo scheduled today', 'Live product demo for CloudKart at 2:00 PM', '/leads/9', 'reminder', FALSE, NOW() - INTERVAL '1 hour'),
(4, 1, 7, 'Proposal follow-up', 'Deliver proposal pricing to Vanguard FinTech', '/opportunities/11', 'reminder', FALSE, NOW() - INTERVAL '4 hours'),
(5, 1, NULL, 'Deal Won! 🎉', 'Elevate Insurance closed won for $560,000', '/opportunities/19', 'update', FALSE, NOW() - INTERVAL '2 days'),
(6, 1, NULL, 'Lead assigned', 'You were assigned new lead: Vikram Singh', '/leads/1', 'update', TRUE, NOW() - INTERVAL '2 days'),
(7, 4, 2, 'Task overdue', 'Send revised NDA to MetroFleet CEO is 2 days overdue', '/tasks', 'reminder', FALSE, NOW() - INTERVAL '2 days'),
(8, 5, 4, 'Task overdue', 'Audit BlueRidge Gear telemetry schema is 5 days overdue', '/tasks', 'reminder', FALSE, NOW() - INTERVAL '5 days')
ON CONFLICT (id) DO NOTHING;

-- 10. EMAIL CAMPAIGNS (Shows metrics in Email Campaigns UI)
INSERT INTO campaigns (id, name, subject, body, status, send_at, created_by_id, created_at, started_at, finished_at) VALUES
(1, 'Q1 Enterprise CRM Solution Launch', 'Streamline your sales cycle with SalesTrack CRM',
 'Hi {{first_name}},\n\nWe recently rolled out our enterprise sales automation platform designed for teams at {{company}}.\n\nWould you be open to a 15-minute introductory call next Tuesday?\n\nBest regards,\nSalesTrack Team',
 'Completed', NOW() - INTERVAL '7 days', 1, NOW() - INTERVAL '8 days', NOW() - INTERVAL '7 days', NOW() - INTERVAL '6 days 22 hours'),

(2, 'Healthcare IT Compliance & Automation', 'HIPAA-compliant CRM workflows for {{company}}',
 'Dear Dr. {{last_name}},\n\nJoin our upcoming live webinar discussing automated compliance audits for medical institutions.\n\nRegister today!\n\nBest,\nHealthcare Solutions Desk',
 'Sending', NOW() - INTERVAL '1 hour', 1, NOW() - INTERVAL '2 days', NOW() - INTERVAL '1 hour', NULL),

(3, 'Summer 2026 Early Bird Product Release', 'Exclusive preview of our AI-powered sales assistant',
 'Hello {{first_name}},\n\nWe are inviting selected enterprise partners to test our automated LinkedIn autofill and deal risk scoring.\n\nLet us know if you want early beta access.\n\nRegards,\nProduct Engineering',
 'Scheduled', NOW() + INTERVAL '5 days', 1, NOW() - INTERVAL '1 day', NULL, NULL)
ON CONFLICT (id) DO NOTHING;

-- 11. CAMPAIGN RECIPIENTS (With Sent, Queued, Invalid, Failed)
INSERT INTO campaign_recipients (campaign_id, lead_id, email, name, company, manual, status, attempts, sent_at, error) VALUES
(1, 1,  'vikram@brightpath.in',       'Vikram Singh',   'BrightPath Schools', FALSE, 'Sent',    1, NOW() - INTERVAL '7 days', NULL),
(1, 5,  'travis@metrofleet.com',      'Travis Kalanick','MetroFleet Tech',    FALSE, 'Sent',    1, NOW() - INTERVAL '7 days', NULL),
(1, 6,  'rgreen@centralperk.com',     'Rachel Green',   'Central Perk',       FALSE, 'Sent',    1, NOW() - INTERVAL '7 days', NULL),
(1, 26, 'adent@hitchhikertravel.com', 'Arthur Dent',    'Hitchhiker Travel',  FALSE, 'Invalid', 1, NULL, '550 5.1.1 User unknown / Mailbox does not exist'),
(1, 27, 'trillian@galaxytech.io',     'Trillian Astra', 'Galaxy Tech',        FALSE, 'Skipped', 0, NULL, 'Recipient opted out / Unsubscribed'),
(2, 3,  'dkim@apexbiosys.com',        'Daniel Kim',     'Apex BioSystems',    FALSE, 'Sent',    1, NOW() - INTERVAL '45 mins', NULL),
(2, 7,  'athorne@nexusgenomics.com',  'Aris Thorne',    'Nexus Genomics',     FALSE, 'Queued',  0, NULL, NULL),
(2, 12, 'scooper@caltechtools.org',   'Sheldon Cooper', 'CalTech Physics',    FALSE, 'Queued',  0, NULL, NULL),
(3, 8,  'gbale@peakperformance.com',  'Gareth Bale',    'Peak Performance',   FALSE, 'Queued',  0, NULL, NULL),
(3, 9,  'rohit@cloudkart.in',         'Rohit Verma',    'CloudKart',          FALSE, 'Queued',  0, NULL, NULL);

-- 12. ACTIVITY LOG (Manage Access & Audit trail)
INSERT INTO activity_log (actor_id, action, target, details, created_at) VALUES
(1, 'User Created',        'Ravi Kumar (ravi@crm.test)',     'Created user with role Salesperson', NOW() - INTERVAL '15 days'),
(1, 'User Created',        'Anita Desai (anita@crm.test)',   'Created user with role Salesperson', NOW() - INTERVAL '15 days'),
(1, 'User Created',        'Priya Sharma (priya@crm.test)',  'Created user with role Manager', NOW() - INTERVAL '15 days'),
(1, 'Permissions Updated', 'Salesperson Role',               'Granted export permission to CSV', NOW() - INTERVAL '10 days'),
(1, 'Lead Transferred',    'BrightPath Schools',             'Transferred lead from Priya Sharma to Administrator', NOW() - INTERVAL '2 days'),
(1, 'Campaign Launched',   'Q1 Enterprise CRM Solution Launch','Sent to 25 recipients via Outlook SMTP', NOW() - INTERVAL '7 days');

-- 13. Update Postgres sequence counters so new records created via UI get safe auto-incrementing IDs
SELECT setval(pg_get_serial_sequence('users', 'id'),             GREATEST((SELECT COALESCE(MAX(id), 1) FROM users), 1));
SELECT setval(pg_get_serial_sequence('accounts', 'id'),          GREATEST((SELECT COALESCE(MAX(id), 1) FROM accounts), 1));
SELECT setval(pg_get_serial_sequence('contacts', 'id'),          GREATEST((SELECT COALESCE(MAX(id), 1) FROM contacts), 1));
SELECT setval(pg_get_serial_sequence('leads', 'id'),             GREATEST((SELECT COALESCE(MAX(id), 1) FROM leads), 1));
SELECT setval(pg_get_serial_sequence('opportunities', 'id'),     GREATEST((SELECT COALESCE(MAX(id), 1) FROM opportunities), 1));
SELECT setval(pg_get_serial_sequence('tasks', 'id'),             GREATEST((SELECT COALESCE(MAX(id), 1) FROM tasks), 1));
SELECT setval(pg_get_serial_sequence('notes', 'id'),             GREATEST((SELECT COALESCE(MAX(id), 1) FROM notes), 1));
SELECT setval(pg_get_serial_sequence('stage_history', 'id'),     GREATEST((SELECT COALESCE(MAX(id), 1) FROM stage_history), 1));
SELECT setval(pg_get_serial_sequence('notifications', 'id'),     GREATEST((SELECT COALESCE(MAX(id), 1) FROM notifications), 1));
SELECT setval(pg_get_serial_sequence('campaigns', 'id'),         GREATEST((SELECT COALESCE(MAX(id), 1) FROM campaigns), 1));
SELECT setval(pg_get_serial_sequence('campaign_recipients', 'id'), GREATEST((SELECT COALESCE(MAX(id), 1) FROM campaign_recipients), 1));
SELECT setval(pg_get_serial_sequence('activity_log', 'id'),      GREATEST((SELECT COALESCE(MAX(id), 1) FROM activity_log), 1));
