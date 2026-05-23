#!/usr/bin/env python3
"""Load Australian state/territory population data into Trino.

Source: ABS 3101.0 Estimated Resident Population (ERP) at 30 June each year.
Mid-year estimates used to align with NNDSS notification year boundaries.

Usage:
    TRINO_HOST=localhost TRINO_PORT=8090 python scripts/load-population-trino.py
"""

import os
from trino.dbapi import connect

TRINO_HOST = os.environ.get("TRINO_HOST", "localhost")
TRINO_PORT = int(os.environ.get("TRINO_PORT", "8080"))

# ABS 3101.0 ERP at 30 June, by state/territory (thousands → actual)
# Source: https://www.abs.gov.au/statistics/people/population/national-state-and-territory-population
POPULATION = [
    # (year, state, population)
    # 2008
    (2008, "NSW", 6943800), (2008, "VIC", 5261700), (2008, "QLD", 4228300),
    (2008, "SA", 1580900), (2008, "WA", 2163300), (2008, "TAS", 498700),
    (2008, "NT", 220000), (2008, "ACT", 345500),
    # 2009
    (2009, "NSW", 7048200), (2009, "VIC", 5367800), (2009, "QLD", 4325300),
    (2009, "SA", 1601600), (2009, "WA", 2230200), (2009, "TAS", 502600),
    (2009, "NT", 224900), (2009, "ACT", 352200),
    # 2010
    (2010, "NSW", 7145900), (2010, "VIC", 5479700), (2010, "QLD", 4425400),
    (2010, "SA", 1622700), (2010, "WA", 2296400), (2010, "TAS", 507600),
    (2010, "NT", 229700), (2010, "ACT", 358900),
    # 2011
    (2011, "NSW", 7218500), (2011, "VIC", 5537800), (2011, "QLD", 4476800),
    (2011, "SA", 1639600), (2011, "WA", 2352200), (2011, "TAS", 511500),
    (2011, "NT", 232400), (2011, "ACT", 367800),
    # 2012
    (2012, "NSW", 7310300), (2012, "VIC", 5624300), (2012, "QLD", 4560100),
    (2012, "SA", 1656700), (2012, "WA", 2430800), (2012, "TAS", 512000),
    (2012, "NT", 236300), (2012, "ACT", 376500),
    # 2013
    (2013, "NSW", 7410700), (2013, "VIC", 5739900), (2013, "QLD", 4653100),
    (2013, "SA", 1670400), (2013, "WA", 2517200), (2013, "TAS", 512700),
    (2013, "NT", 241400), (2013, "ACT", 383400),
    # 2014
    (2014, "NSW", 7519700), (2014, "VIC", 5866300), (2014, "QLD", 4722400),
    (2014, "SA", 1685700), (2014, "WA", 2573400), (2014, "TAS", 514700),
    (2014, "NT", 244600), (2014, "ACT", 390500),
    # 2015
    (2015, "NSW", 7618200), (2015, "VIC", 5996400), (2015, "QLD", 4779400),
    (2015, "SA", 1698500), (2015, "WA", 2574600), (2015, "TAS", 516600),
    (2015, "NT", 244500), (2015, "ACT", 395200),
    # 2016
    (2016, "NSW", 7739800), (2016, "VIC", 6179200), (2016, "QLD", 4848900),
    (2016, "SA", 1710800), (2016, "WA", 2558000), (2016, "TAS", 518500),
    (2016, "NT", 245600), (2016, "ACT", 403500),
    # 2017
    (2017, "NSW", 7861100), (2017, "VIC", 6323600), (2017, "QLD", 4929200),
    (2017, "SA", 1723500), (2017, "WA", 2580400), (2017, "TAS", 521500),
    (2017, "NT", 247500), (2017, "ACT", 411700),
    # 2018
    (2018, "NSW", 7971700), (2018, "VIC", 6462000), (2018, "QLD", 5011200),
    (2018, "SA", 1736400), (2018, "WA", 2603900), (2018, "TAS", 526100),
    (2018, "NT", 247600), (2018, "ACT", 420900),
    # 2019
    (2019, "NSW", 8089500), (2019, "VIC", 6594800), (2019, "QLD", 5095100),
    (2019, "SA", 1751700), (2019, "WA", 2621700), (2019, "TAS", 534300),
    (2019, "NT", 245600), (2019, "ACT", 428100),
    # 2020
    (2020, "NSW", 8166400), (2020, "VIC", 6694900), (2020, "QLD", 5184800),
    (2020, "SA", 1770600), (2020, "WA", 2667100), (2020, "TAS", 541500),
    (2020, "NT", 246500), (2020, "ACT", 431800),
    # 2021
    (2021, "NSW", 8095400), (2021, "VIC", 6503500), (2021, "QLD", 5217400),
    (2021, "SA", 1773600), (2021, "WA", 2681600), (2021, "TAS", 551800),
    (2021, "NT", 249800), (2021, "ACT", 454500),
    # 2022
    (2022, "NSW", 8238800), (2022, "VIC", 6613700), (2022, "QLD", 5322600),
    (2022, "SA", 1800200), (2022, "WA", 2736700), (2022, "TAS", 557300),
    (2022, "NT", 253100), (2022, "ACT", 456800),
    # 2023
    (2023, "NSW", 8414000), (2023, "VIC", 6797000), (2023, "QLD", 5464000),
    (2023, "SA", 1833000), (2023, "WA", 2836000), (2023, "TAS", 558000),
    (2023, "NT", 257000), (2023, "ACT", 464000),
    # 2024
    (2024, "NSW", 8519000), (2024, "VIC", 6982000), (2024, "QLD", 5595000),
    (2024, "SA", 1887000), (2024, "WA", 2996000), (2024, "TAS", 575000),
    (2024, "NT", 262000), (2024, "ACT", 474000),
    # 2025 (projected, Sep 2025 ABS release)
    (2025, "NSW", 8625000), (2025, "VIC", 7104000), (2025, "QLD", 5693000),
    (2025, "SA", 1908000), (2025, "WA", 3062000), (2025, "TAS", 577000),
    (2025, "NT", 265000), (2025, "ACT", 482000),
]


def main():
    print(f"Connecting to Trino at {TRINO_HOST}:{TRINO_PORT}")
    conn = connect(host=TRINO_HOST, port=TRINO_PORT, user="admin",
                   catalog="lakehouse", schema="nndss")
    cur = conn.cursor()

    print("Creating population table...")
    cur.execute("DROP TABLE IF EXISTS lakehouse.nndss.population")
    cur.execute("""
        CREATE TABLE lakehouse.nndss.population (
            year INTEGER,
            state VARCHAR,
            population INTEGER
        )
    """)

    # Batch insert
    batch_size = 500
    for start in range(0, len(POPULATION), batch_size):
        batch = POPULATION[start:start + batch_size]
        values = ", ".join(
            f"({yr}, '{st}', {pop})" for yr, st, pop in batch
        )
        cur.execute(f"INSERT INTO lakehouse.nndss.population VALUES {values}")

    print(f"Inserted {len(POPULATION)} rows")

    # Verify
    cur.execute("""
        SELECT year, state, population
        FROM lakehouse.nndss.population
        WHERE year = 2023
        ORDER BY population DESC
    """)
    print("\n2023 population by state:")
    for row in cur.fetchall():
        print(f"  {row[1]}: {row[2]:,}")

    # Test per-capita query
    cur.execute("""
        SELECT n.state, n.disease, n.notifications, p.population,
               ROUND(100000.0 * n.notifications / p.population, 1) AS rate_per_100k
        FROM lakehouse.nndss.notifications n
        JOIN lakehouse.nndss.population p
          ON n.state = p.state AND n.year = p.year
        WHERE n.year = 2023 AND n.disease = 'Influenza (laboratory confirmed)'
        ORDER BY rate_per_100k DESC
    """)
    print("\n2023 influenza rate per 100,000:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[2]:,} notifications / {row[3]:,} pop = {row[4]} per 100k")

    print("\nDone!")
    conn.close()


if __name__ == "__main__":
    main()
