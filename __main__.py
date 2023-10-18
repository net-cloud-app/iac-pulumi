import pulumi
import pulumi_aws 
from pulumi_aws import ec2, Provider, get_availability_zones, Provider
import ipaddress
import boto3


# print("hi")

aws_profile=pulumi.Config("aws").require("profile")
aws_vpccidr = pulumi.Config("vpc").require("cidrBlock")
aws_region=pulumi.Config("aws").require("region")
key_pair_name=pulumi.Config("vpc").require("ssh_key_pair")
port_no=pulumi.Config("vpc").require("port_no")

# Create a new VPC
vpc = ec2.Vpc("vpc",
            cidr_block=aws_vpccidr,
            enable_dns_support=True,
            enable_dns_hostnames=True,
            tags={
              "Name": "New_VPC",
            },

              
              
)

# Create a new Internet Gateway and a 
# 
# Attach it to the VPC
gateway = ec2.InternetGateway("gateway",
                            vpc_id=vpc.id,
                            tags={
                              "Name": "main-gateway",
                            },

)
az_list = pulumi.Config("vpc").require("availabilityZones").split(',')
print(f"inputazs{az_list}")
available_azs = get_availability_zones(state="available").names
print (f"available_azs{available_azs}")

invalid_azs = [az for az in az_list if az not in available_azs]

try:
    if invalid_azs:
        raise ValueError(f"Invalid availability zone(s): {', '.join(invalid_azs)}")


    desired_az_count = min(3, len(az_list))
    print(desired_az_count)
    
    # Calculate subnet CIDR blocks dynamically based on desired AZs
    vpc_cidr = ipaddress.ip_network(aws_vpccidr)
    subnet_cidr_blocks = list(vpc_cidr.subnets(new_prefix=24))[:desired_az_count+5]

    
        # Create a public subnet in each availability zone
    public_subnets = [ec2.Subnet(f"public-subnet-{i+1}",
        vpc_id=vpc.id,
        cidr_block=str(subnet_cidr_blocks[i]),
        map_public_ip_on_launch=True,
        availability_zone=az,
        tags={
            "Name": f"public-subnet-{i+1}",
        }
    ) for i, az in enumerate(az_list)]

    # Create a private subnet in each availability zone
    private_subnets = [ec2.Subnet(f"private-subnet-{i+1}",
        vpc_id=vpc.id,
        cidr_block=str(subnet_cidr_blocks[i+4]),
        map_public_ip_on_launch=False,
        availability_zone=az,
        tags={
            "Name": f"private-subnet-{i+1}",
        }
    ) for i, az in enumerate(az_list)]

   
    
    # Create a public Route Table
    public_route_table = ec2.RouteTable("public-route-table",
        vpc_id=vpc.id,
        tags={
            "Name": "Public Route Table",
        }
    )

    # Create a private Route Table
    private_route_table = ec2.RouteTable("private-route-table",
        vpc_id=vpc.id,
        tags={
            "Name": "Private Route Table",
        }
    )

    # Associate public subnets with the public route table
    for i, subnet in enumerate(public_subnets):
        ec2.RouteTableAssociation(f"public-subnet-association-{i}",
            subnet_id=subnet.id,
            route_table_id=public_route_table.id,
        )

    # Associate private subnets with the private route table
    for i, subnet in enumerate(private_subnets):
        ec2.RouteTableAssociation(f"private-subnet-association-{i}",
            subnet_id=subnet.id,
            route_table_id=private_route_table.id,
        )

    # Create a Route in the public route table to direct traffic to the Internet Gateway
    ec2.Route("public-route",
        route_table_id=public_route_table.id,
        destination_cidr_block="0.0.0.0/0",
        gateway_id=gateway.id,  # Connect to the Internet Gateway
    )

    
    # Create the application security group
    app_security_group = ec2.SecurityGroup("app-security-group",
        vpc_id=vpc.id,
        tags={
            "Name": "Application Security Group",
        }
    )

    app_security_group_rule_ssh = ec2.SecurityGroupRule("app-security-group-rule-ssh",
    type="ingress",
    from_port=22,
    to_port=22,
    protocol="tcp",
    cidr_blocks=["0.0.0.0/0"],  # Allow from anywhere
    security_group_id=app_security_group.id,
    ) 
    app_security_group_rule_http = ec2.SecurityGroupRule("app-security-group-rule-http",
    type="ingress",
    from_port=80,
    to_port=80,
    protocol="tcp",
    cidr_blocks=["0.0.0.0/0"],  # Allow from anywhere
    security_group_id=app_security_group.id,
    )

    app_security_group_rule_https = ec2.SecurityGroupRule("app-security-group-rule-https",
        type="ingress",
        from_port=443,
        to_port=443,
        protocol="tcp",
        cidr_blocks=["0.0.0.0/0"],  # Allow from anywhere
        security_group_id=app_security_group.id,
    )

    # Replace 'APP_PORT' with your application's specific port
    app_port = port_no
    app_security_group_rule_app = ec2.SecurityGroupRule("app-security-group-rule-app",
        type="ingress",
        from_port=app_port,
        to_port=app_port,
        protocol="tcp",
        cidr_blocks=["0.0.0.0/0"],  # Allow from anywhere
        security_group_id=app_security_group.id,
    )    
        # Your custom AMI name
    # custom_ami_name = "debian12-custom-ami"  # Replace with your AMI name

    # Create an AWS EC2 client using boto3
    ec2_client = boto3.session.Session(profile_name=aws_profile).client("ec2")
    # Use boto3 to search for the custom AMI
    response = ec2_client.describe_images(ExecutableUsers=['self'], Filters=[{'Name': 'image-type', 'Values': ['machine']}])
    sorted_images = sorted(response['Images'], key=lambda x: x['CreationDate'], reverse=True)

    custom_ami_id=0
    if sorted_images:
        custom_ami_id = sorted_images[0]['ImageId']
        print(f"Latest AMI ID (based on creation time): {custom_ami_id}")
    else:
        print("No AMIs found.")

    if custom_ami_id:
        # The custom AMI was found
        custom_ami_id = custom_ami_id

        outbound_rule = ec2.SecurityGroupRule("outbound-rule",
            type="egress",
            from_port=8000,
            to_port=8000,
            protocol="tcp",
            cidr_blocks=["0.0.0.0/0"],
            security_group_id=app_security_group.id,
        )
        

        

        
        ec2_instance = ec2.Instance("ec2-instance",
            ami=custom_ami_id,
            instance_type="t2.micro",
            subnet_id=public_subnets[0].id,
            security_groups=[app_security_group.id],
            key_name=key_pair_name,  # Attach the key pair

            associate_public_ip_address=True,
            tags={
                "Name": "MyEC2Instance",
            },
            root_block_device=ec2.InstanceRootBlockDeviceArgs(
                volume_size=25,
                volume_type='gp2',
                delete_on_termination=True,
             ),
            disable_api_termination=False,
        )
        
    else:
        print("Custom AMI not found.")
except ValueError as e:
    print(f"An error occurred: {e}")
pulumi.export('vpc_id', vpc.id)