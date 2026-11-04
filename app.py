
import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
from supabase import create_client, Client

# --------------------------------------------------
# PAGE CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="Kigali Smart Bus Reservation",
    page_icon="🚌",
    layout="wide"
)

# --------------------------------------------------
# CONNECT TO SUPABASE
# --------------------------------------------------

@st.cache_resource
def connect_database():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase: Client = connect_database()
except Exception as error:
    st.error("Database connection is not configured correctly.")
    st.info(
        "We still need to add the Supabase connection details "
        "in Streamlit Cloud Secrets."
    )
    st.stop()


# --------------------------------------------------
# DATABASE FUNCTIONS
# --------------------------------------------------

def get_data(table):
    response = supabase.table(table).select("*").execute()
    return response.data or []


def get_bus_routes(bus_id):
    route_rows = (
        supabase.table("bus_route_stops")
        .select("*")
        .eq("bus_id", bus_id)
        .order("stop_order")
        .execute()
    ).data or []

    stops = get_data("bus_stops")
    stop_lookup = {stop["id"]: stop for stop in stops}

    route = []

    for item in route_rows:
        stop = stop_lookup.get(item["stop_id"])

        if stop:
            route.append({
                "id": stop["id"],
                "name": stop["name"],
                "order": item["stop_order"]
            })

    return route


def get_confirmed_reservations(bus_id):
    return (
        supabase.table("reservations")
        .select("*")
        .eq("bus_id", bus_id)
        .eq("status", "confirmed")
        .execute()
    ).data or []


def calculate_available_seats(bus, route, boarding_id, destination_id):
    """
    Calculate available seats on every route segment.
    A seat is occupied only on the part of the route
    where that passenger is travelling.
    """

    route_order = {stop["id"]: stop["order"] for stop in route}

    start_order = route_order.get(boarding_id)
    end_order = route_order.get(destination_id)

    if start_order is None or end_order is None:
        return 0

    if start_order >= end_order:
        return 0

    reservations = get_confirmed_reservations(bus["id"])
    segment_occupancy = []

    for segment in range(start_order, end_order):
        occupied = 0

        for reservation in reservations:
            passenger_start = route_order.get(
                reservation["boarding_stop_id"]
            )
            passenger_end = route_order.get(
                reservation["destination_stop_id"]
            )

            if passenger_start is None or passenger_end is None:
                continue

            if passenger_start <= segment < passenger_end:
                occupied += 1

        segment_occupancy.append(occupied)

    maximum_occupancy = max(segment_occupancy, default=0)

    return max(0, bus["capacity"] - maximum_occupancy)


def find_or_create_passenger(full_name, phone):
    existing = (
        supabase.table("passengers")
        .select("*")
        .eq("phone_number", phone)
        .limit(1)
        .execute()
    ).data or []

    if existing:
        passenger = existing[0]

        if passenger["full_name"] != full_name:
            supabase.table("passengers").update({
                "full_name": full_name
            }).eq("id", passenger["id"]).execute()

        return passenger["id"]

    result = supabase.table("passengers").insert({
        "full_name": full_name,
        "phone_number": phone
    }).execute()

    return result.data[0]["id"]


def make_booking_reference():
    return "KSB-" + uuid.uuid4().hex[:8].upper()


# --------------------------------------------------
# HEADER
# --------------------------------------------------

st.title("🚌 Kigali Smart Bus-Stop Reservation")
st.caption(
    "Smart Bus-Stop Reservation and Passenger Demand "
    "Prediction System"
)

st.markdown(
    "Welcome! Use this platform to reserve a bus seat, "
    "check available seats and manage bus reservations."
)

# --------------------------------------------------
# SIDEBAR NAVIGATION
# --------------------------------------------------

page = st.sidebar.radio(
    "Navigation",
    [
        "Passenger Booking",
        "Cancel Booking",
        "Driver Dashboard",
        "Bus Information"
    ]
)

st.sidebar.divider()
st.sidebar.info(
    "Kigali Smart Transport\n\n"
    "Online bus reservation prototype"
)

# --------------------------------------------------
# LOAD BUSES
# --------------------------------------------------

buses = get_data("buses")
active_buses = [bus for bus in buses if bus.get("is_active", True)]

if not active_buses:
    st.error("No active buses are currently available.")
    st.stop()

bus_lookup = {
    bus["bus_code"]: bus for bus in active_buses
}

# --------------------------------------------------
# PASSENGER BOOKING
# --------------------------------------------------

if page == "Passenger Booking":

    st.header("Passenger Seat Booking")

    bus_code = st.selectbox(
        "Select your bus",
        list(bus_lookup.keys())
    )

    selected_bus = bus_lookup[bus_code]
    route = get_bus_routes(selected_bus["id"])

    if len(route) < 2:
        st.warning("This bus does not have a complete route yet.")
        st.stop()

    stop_names = [stop["name"] for stop in route]

    stop_lookup = {
        stop["name"]: stop for stop in route
    }

    col1, col2 = st.columns(2)

    with col1:
        boarding_name = st.selectbox(
            "Boarding bus stop",
            stop_names,
            index=0
        )

    boarding_order = stop_lookup[boarding_name]["order"]

    possible_destinations = [
        stop["name"]
        for stop in route
        if stop["order"] > boarding_order
    ]

    with col2:
        destination_name = st.selectbox(
            "Destination",
            possible_destinations
        )

    boarding_id = stop_lookup[boarding_name]["id"]
    destination_id = stop_lookup[destination_name]["id"]

    available_seats = calculate_available_seats(
        selected_bus,
        route,
        boarding_id,
        destination_id
    )

    st.divider()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Bus", bus_code)

    with col2:
        st.metric("Total capacity", selected_bus["capacity"])

    with col3:
        st.metric("Available seats", available_seats)

    if available_seats > 0:

        st.success(
            f"{available_seats} seat(s) available for your journey."
        )

        with st.form("passenger_booking_form"):

            full_name = st.text_input("Passenger full name")
            phone = st.text_input(
                "Phone number",
                placeholder="Example: 078xxxxxxx"
            )

            agree = st.checkbox(
                "I confirm that the booking information is correct."
            )

            submitted = st.form_submit_button(
                "Confirm Seat Reservation",
                use_container_width=True
            )

            if submitted:

                if not full_name.strip():
                    st.error("Please enter your full name.")

                elif not phone.strip():
                    st.error("Please enter your phone number.")

                elif not agree:
                    st.error("Please confirm your booking information.")

                else:
                    try:
                        passenger_id = find_or_create_passenger(
                            full_name.strip(),
                            phone.strip()
                        )

                        # Recheck availability before saving.
                        latest_seats = calculate_available_seats(
                            selected_bus,
                            route,
                            boarding_id,
                            destination_id
                        )

                        if latest_seats <= 0:
                            st.error(
                                "Sorry, the remaining seats have just "
                                "been reserved. Please choose another bus."
                            )
                        else:
                            reference = make_booking_reference()

                            supabase.table("reservations").insert({
                                "booking_reference": reference,
                                "passenger_id": passenger_id,
                                "bus_id": selected_bus["id"],
                                "boarding_stop_id": boarding_id,
                                "destination_stop_id": destination_id,
                                "booking_source": "mobile",
                                "status": "confirmed"
                            }).execute()

                            st.success("Your reservation was successful!")

                            st.subheader("Your Booking Details")
                            st.write(f"**Reference:** {reference}")
                            st.write(f"**Passenger:** {full_name}")
                            st.write(f"**Bus:** {bus_code}")
                            st.write(f"**Boarding:** {boarding_name}")
                            st.write(f"**Destination:** {destination_name}")

                            st.warning(
                                "Keep your booking reference safe. "
                                "This prototype does not yet send SMS "
                                "or generate QR tickets."
                            )

                    except Exception as error:
                        st.error("The reservation could not be completed.")
                        st.code(str(error))

    else:
        st.error(
            "No seats are available for this journey. "
            "Please choose another bus or journey."
        )


# --------------------------------------------------
# CANCEL BOOKING
# --------------------------------------------------

elif page == "Cancel Booking":

    st.header("Cancel a Reservation")

    st.write(
        "Enter your booking reference and the phone number "
        "used when making the reservation."
    )

    with st.form("cancel_form"):

        reference = st.text_input("Booking reference")
        phone = st.text_input("Passenger phone number")

        cancel_button = st.form_submit_button(
            "Find My Reservation"
        )

    if cancel_button:

        try:
            passenger = (
                supabase.table("passengers")
                .select("*")
                .eq("phone_number", phone.strip())
                .limit(1)
                .execute()
            ).data or []

            if not passenger:
                st.error("Passenger record was not found.")

            else:
                booking = (
                    supabase.table("reservations")
                    .select("*")
                    .eq("booking_reference", reference.strip().upper())
                    .eq("passenger_id", passenger[0]["id"])
                    .eq("status", "confirmed")
                    .limit(1)
                    .execute()
                ).data or []

                if not booking:
                    st.error(
                        "No active reservation matches those details."
                    )

                else:
                    reservation = booking[0]

                    if st.button(
                        "Confirm Cancellation",
                        type="primary"
                    ):
                        supabase.table("reservations").update({
                            "status": "cancelled"
                        }).eq(
                            "id", reservation["id"]
                        ).execute()

                        st.success("Your booking has been cancelled.")
                        st.rerun()

        except Exception as error:
            st.error("Unable to process cancellation.")
            st.code(str(error))


# --------------------------------------------------
# DRIVER DASHBOARD
# --------------------------------------------------

elif page == "Driver Dashboard":

    st.header("Driver Dashboard")

    selected_code = st.selectbox(
        "Select your bus",
        list(bus_lookup.keys()),
        key="driver_bus"
    )

    selected_bus = bus_lookup[selected_code]
    route = get_bus_routes(selected_bus["id"])

    reservations = get_confirmed_reservations(
        selected_bus["id"]
    )

    passengers = get_data("passengers")
    passenger_lookup = {
        passenger["id"]: passenger
        for passenger in passengers
    }

    stops = get_data("bus_stops")
    stop_lookup = {
        stop["id"]: stop["name"]
        for stop in stops
    }

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Bus capacity", selected_bus["capacity"])

    with col2:
        st.metric("Confirmed reservations", len(reservations))

    with col3:
        st.metric(
            "Remaining first-segment seats",
            calculate_available_seats(
                selected_bus,
                route,
                route[0]["id"],
                route[1]["id"]
            ) if len(route) >= 2 else 0
        )

    st.subheader("Reservations by Boarding Stop")

    stop_counts = []

    for stop in route:
        count = sum(
            1 for reservation in reservations
            if reservation["boarding_stop_id"] == stop["id"]
        )

        stop_counts.append({
            "Bus stop": stop["name"],
            "Passengers boarding": count
        })

    if stop_counts:
        st.dataframe(
            pd.DataFrame(stop_counts),
            use_container_width=True,
            hide_index=True
        )

    st.subheader("Passenger Reservations")

    if reservations:

        booking_rows = []

        for reservation in reservations:

            passenger = passenger_lookup.get(
                reservation.get("passenger_id"), {}
            )

            booking_rows.append({
                "Reference": reservation["booking_reference"],
                "Passenger": passenger.get("full_name", "Unknown"),
                "Phone": passenger.get("phone_number", "Not available"),
                "Boarding stop": stop_lookup.get(
                    reservation["boarding_stop_id"], "Unknown"
                ),
                "Destination": stop_lookup.get(
                    reservation["destination_stop_id"], "Unknown"
                ),
                "Source": reservation["booking_source"]
            })

        st.dataframe(
            pd.DataFrame(booking_rows),
            use_container_width=True,
            hide_index=True
        )

    else:
        st.info("There are no confirmed reservations for this bus.")

    st.caption(
        "This dashboard displays current confirmed bookings. "
        "Live GPS tracking and automatic journey reset will be added later."
    )


# --------------------------------------------------
# BUS INFORMATION AND DEMAND INDICATOR
# --------------------------------------------------

elif page == "Bus Information":

    st.header("Bus Information")

    for bus in active_buses:

        route = get_bus_routes(bus["id"])

        route_text = " → ".join(
            stop["name"] for stop in route
        )

        st.subheader(bus["bus_code"])
        st.write(f"**Capacity:** {bus['capacity']} passengers")
        st.write(f"**Route:** {route_text}")

        reservations = get_confirmed_reservations(bus["id"])

        st.write(
            f"**Current confirmed bookings:** {len(reservations)}"
        )

        st.divider()

    st.subheader("Passenger Demand Indicator")

    st.caption(
        "This is an initial booking-based indicator, not yet a trained "
        "machine-learning prediction."
    )

    all_reservations = [
        reservation
        for reservation in get_data("reservations")
        if reservation["status"] == "confirmed"
    ]

    stops = get_data("bus_stops")

    demand_rows = []

    for stop in stops:

        count = sum(
            1 for reservation in all_reservations
            if reservation["boarding_stop_id"] == stop["id"]
        )

        if count >= 6:
            level = "High"
        elif count >= 3:
            level = "Medium"
        else:
            level = "Low"

        demand_rows.append({
            "Bus stop": stop["name"],
            "Current confirmed bookings": count,
            "Demand indicator": level
        })

    st.dataframe(
        pd.DataFrame(demand_rows),
        use_container_width=True,
        hide_index=True
    )

    st.info(
        "In a later version, we will train a machine-learning model "
        "to predict future passenger demand using historical bookings."
    )


# --------------------------------------------------
# FOOTER
# --------------------------------------------------

st.divider()

st.caption(
    "Kigali Smart Bus-Stop Reservation and Passenger "
    "Demand Prediction System | Prototype Version 1"
)
