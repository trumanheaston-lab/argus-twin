from skyfield.api import load, wgs84

# 1. Define Ground Station Location (Dripping Springs, TX)
dripping_springs = wgs84.latlon(30.1902, -98.0867, elevation_m=350)

# 2. Setup TLE Source and Cache Path
tle_url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle'
tle_filename = 'data/iss_stations.tle'

ts = load.timescale()

# 3. Load and cache TLE data automatically
satellites = load.tle_file(tle_url, filename=tle_filename)

# Grab the ISS from the loaded list
iss = [sat for sat in satellites if 'ISS' in sat.name.upper()][0]

# 4. Compute Current Difference Vectors (Alt / Az / Distance)
now = ts.now()
difference = iss - dripping_springs
topocentric = difference.at(now)
alt, az, distance = topocentric.altaz()

# 5. Output Real-Time Coordinates
print("\n--- Real-Time Satellite Tracking Data ---")
print(f"Target:       {iss.name}")
print(f"Time (UTC):   {now.utc_strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Azimuth:      {az.degrees:.2f}° (Pan motor coordinate)")
print(f"Altitude:     {alt.degrees:.2f}° (Tilt motor coordinate)")
print(f"Range:        {distance.km:.1f} km")

if alt.degrees > 0:
    print("STATUS:       ABOVE HORIZON (Visible / Trackable)")
else:
    print("STATUS:       BELOW HORIZON")